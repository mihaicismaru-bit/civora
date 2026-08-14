#!/usr/bin/env python3
"""Fail-closed validator for VÂLCEA CLAR local business data."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 8, 14)
PRICE_MAX_AGE_DAYS = 120
ALLOWED_PUBLIC_SOURCE_KINDS = {"official_site", "official_legal", "reputable_press"}


def load(name: str) -> dict:
    with (ROOT / "data" / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def valid_https(url: str | None) -> bool:
    if not url:
        return True
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc)


def as_date(value: str | None, field: str, errors: list[str]) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{field}: dată ISO invalidă: {value}")
        return None


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    source_doc = load("sources.json")
    place_doc = load("places.json")
    creator_doc = load("creators.json")

    source_ids: set[str] = set()
    sources: dict[str, dict] = {}
    for source in source_doc.get("sources", []):
        sid = source.get("id")
        if not sid:
            errors.append("source fără id")
            continue
        if sid in source_ids:
            errors.append(f"source id duplicat: {sid}")
        source_ids.add(sid)
        sources[sid] = source
        if not valid_https(source.get("url")):
            errors.append(f"{sid}: URL-ul trebuie să fie HTTPS")
        score = source.get("authority_score")
        if not isinstance(score, int) or not 0 <= score <= 100:
            errors.append(f"{sid}: authority_score trebuie să fie 0–100")
        as_date(source.get("last_checked_at"), f"{sid}.last_checked_at", errors)

    place_ids: set[str] = set()
    slugs: set[str] = set()
    for place in place_doc.get("places", []):
        pid = place.get("id", "<fără-id>")
        if pid in place_ids:
            errors.append(f"place id duplicat: {pid}")
        place_ids.add(pid)
        slug = place.get("slug")
        if slug in slugs:
            errors.append(f"slug duplicat: {slug}")
        slugs.add(slug)

        refs = place.get("source_ids", [])
        missing = [sid for sid in refs if sid not in sources]
        if missing:
            errors.append(f"{pid}: surse inexistente: {', '.join(missing)}")

        if place.get("publication_status") == "public":
            if place.get("verification_level") == "candidate":
                errors.append(f"{pid}: candidatul nu poate fi public")
            if not refs:
                errors.append(f"{pid}: localul public trebuie să aibă surse")
            authoritative = [sid for sid in refs if sources.get(sid, {}).get("kind") in ALLOWED_PUBLIC_SOURCE_KINDS]
            if not authoritative:
                errors.append(f"{pid}: localul public nu are sursă oficială sau presă reputabilă")
            location = place.get("location", {})
            if not location.get("address") or not location.get("city"):
                errors.append(f"{pid}: localul public trebuie să aibă adresă și oraș")
            if not place.get("last_verified_at"):
                errors.append(f"{pid}: lipsește data ultimei verificări")

        contact = place.get("contact", {})
        if not valid_https(contact.get("website")):
            errors.append(f"{pid}: website invalid sau non-HTTPS")

        op = place.get("operator", {})
        if op.get("verification_status") == "verified":
            if not op.get("legal_name"):
                errors.append(f"{pid}: operator verificat fără denumire juridică")
            op_refs = op.get("source_ids", [])
            if not op_refs:
                errors.append(f"{pid}: operator verificat fără sursă")
            for sid in op_refs:
                if sid not in sources:
                    errors.append(f"{pid}: sursa operatorului nu există: {sid}")

        menu = place.get("offer", {}).get("menu", {})
        menu_refs = menu.get("source_ids", [])
        for sid in menu_refs:
            if sid not in sources:
                errors.append(f"{pid}: sursa meniului nu există: {sid}")
        if menu.get("prices_public"):
            checked = as_date(menu.get("checked_at"), f"{pid}.menu.checked_at", errors)
            if checked is None:
                errors.append(f"{pid}: prețuri publice fără dată")
            elif (TODAY - checked).days > PRICE_MAX_AGE_DAYS:
                errors.append(f"{pid}: prețurile au depășit {PRICE_MAX_AGE_DAYS} zile")
            if not menu_refs:
                errors.append(f"{pid}: prețuri publice fără surse")
            for sid in menu_refs:
                if sources.get(sid, {}).get("kind") not in {"official_site", "official_legal"}:
                    errors.append(f"{pid}: preț public bazat pe sursă neoficială: {sid}")
            for item in menu.get("sample_prices", []):
                if not item.get("item") or not isinstance(item.get("price_ron"), (int, float)):
                    errors.append(f"{pid}: eșantion de preț incomplet")
                sid = item.get("source_id")
                if sid not in menu_refs:
                    errors.append(f"{pid}: prețul {item.get('item')} nu indică o sursă a meniului")

        place_hours = place.get("hours", {})
        if place_hours.get("status", "").startswith("verified") and not place_hours.get("source_ids"):
            errors.append(f"{pid}: program verificat fără sursă")

    public_creators = [c for c in creator_doc.get("creators", []) if c.get("publication_status") == "public"]
    threshold = creator_doc.get("policy", {}).get("public_threshold", 75)
    minimum = creator_doc.get("policy", {}).get("minimum_independent_evidence", 2)
    for creator in public_creators:
        cid = creator.get("id", "<fără-id>")
        if creator.get("score", 0) < threshold:
            errors.append(f"{cid}: creator public sub pragul de {threshold}")
        refs = creator.get("source_ids", [])
        if len(set(refs)) < minimum:
            errors.append(f"{cid}: creator public fără minimum {minimum} dovezi")
        evidence = creator.get("evidence", {})
        for signal in ("local_food_content", "official_profile", "commercial_disclosure_review"):
            if evidence.get(signal) is not True:
                errors.append(f"{cid}: lipsește semnalul obligatoriu {signal}")

    if not public_creators:
        warnings.append("Food Creator Index rămâne privat: niciun creator nu a trecut încă pragul editorial.")

    print(f"Validated {len(sources)} sources, {len(place_ids)} places, {len(public_creators)} public creators.")
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("VÂLCEA CLAR quality gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
