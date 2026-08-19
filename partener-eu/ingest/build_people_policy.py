#!/usr/bin/env python3
"""Build automated 'Ce spun decidenții' data for PARTENER.EU.

The builder is the trust boundary for person-level signals. It combines verified
seeds, canonical decision products and the durable direct-official-source ledger.
Statements remain signals until separately corroborated by T1/T1B administrative
evidence. A historical official observation keeps the role snapshot verified at
observation time; it is not silently rewritten to the person's current role.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import ssl
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_registry.json"
SEED = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_seed.json"
OFFICIAL = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_official_sources.json"
MIPE = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
DECISIONS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JSON = ROOT / "partener-eu" / "ingest" / "state" / "people_policy.json"
OUT_JS = ROOT / "partener-eu" / "web" / "people-policy-data.js"
UA = "PARTENER.EU-PeoplePolicy/3.0 (+https://partener.eu)"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.I)


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def clean(s: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(s or ""))).strip()


def norm(s: Any) -> str:
    return clean(s).lower().translate(str.maketrans("ăâîșşțţ", "aaisstt"))


def date_key(value: Any) -> str:
    text = str(value or "")
    m = re.match(r"(20\d{2}-\d{2}-\d{2})", text)
    return m.group(1) if m else "1970-01-01"


def type_for(text: str) -> str:
    t = norm(text)
    if any(x in t for x in ("prelung", "termen", "modific", "ghid", "calendar")):
        return "PROGRAMME_CHANGE_SIGNAL"
    if any(x in t for x in ("buget", "aloc", "finant", "grant", "milioane", "miliarde")):
        return "FUNDING_COMMITMENT"
    return "POLICY_SIGNAL"


def role_snapshot(person: dict[str, Any]) -> dict[str, Any] | None:
    verification = person.get("roleVerification")
    if not isinstance(verification, dict) or verification.get("status") != "VERIFIED":
        return None
    return persisted_role_snapshot({
        "role": person.get("role"),
        "institution": person.get("institution"),
        "verifiedAt": verification.get("verifiedAt"),
        "sourceUrl": verification.get("sourceUrl"),
        "sourceTier": verification.get("sourceTier"),
    })


def persisted_role_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    role = clean(value.get("role"))
    institution = clean(value.get("institution"))
    verified_at = clean(value.get("verifiedAt"))
    source_url = clean(value.get("sourceUrl"))
    source_tier = clean(value.get("sourceTier"))
    if not role or not institution or not verified_at:
        return None
    if not source_url.startswith("https://") or not source_tier.startswith("T1"):
        return None
    return {
        "role": role,
        "institution": institution,
        "verifiedAt": verified_at,
        "sourceUrl": source_url,
        "sourceTier": source_tier,
    }


def trusted_official_item(item: Any, tracked_people: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Validate one durable official-ledger observation fail-closed.

    The persisted role snapshot is authoritative for the observation time. We
    require the actor to remain a known tracked person, but deliberately do not
    rewrite or compare the historical role with the current registry role.
    """
    if not isinstance(item, dict) or item.get("officialIngested") is not True:
        return None
    person_id = clean(item.get("personId"))
    if not person_id or person_id not in tracked_people:
        return None
    if item.get("signalKind") != "STATEMENT_SIGNAL":
        return None
    admin = item.get("administrativeFact")
    if not isinstance(admin, dict) or admin.get("status") != "UNCONFIRMED_FROM_SIGNAL" or admin.get("failClosed") is not True:
        return None
    role = persisted_role_snapshot(item.get("roleVerification"))
    if not role:
        return None
    if date_key(item.get("date")) == "1970-01-01":
        return None
    if not all(clean(item.get(k)) for k in ("headline", "statement", "analysis", "watch", "topic")):
        return None
    audiences = item.get("audiences")
    if not isinstance(audiences, list) or not any(clean(x) for x in audiences):
        return None
    sources = item.get("sources")
    if not isinstance(sources, list) or not sources or not isinstance(sources[0], dict):
        return None
    source = sources[0]
    source_url = clean(source.get("url"))
    source_tier = clean(source.get("tier"))
    if not source_url.startswith("https://") or not source_tier.startswith("T1"):
        return None
    snapshot = item.get("sourceSnapshot")
    if not isinstance(snapshot, dict):
        return None
    if clean(snapshot.get("url")) != source_url:
        return None
    if not clean(snapshot.get("sourceId")) or not clean(snapshot.get("publisher")):
        return None
    if not clean(snapshot.get("tier")).startswith("T1") or not clean(snapshot.get("observedAt")):
        return None
    if not SHA256_RE.fullmatch(clean(snapshot.get("contentHash"))):
        return None
    if not SHA256_RE.fullmatch(clean(item.get("fingerprint"))):
        return None
    canonical = item.get("canonicalLink")
    if not isinstance(canonical, dict) or canonical.get("status") not in {"UNRESOLVED", "MATCHED_EXPLICIT_CODE"}:
        return None
    if canonical.get("status") == "MATCHED_EXPLICIT_CODE" and not (clean(canonical.get("callId")) and clean(canonical.get("code"))):
        return None
    out = dict(item)
    out["roleVerification"] = role
    out["personId"] = person_id
    return out


def fetch_og_image(url: str) -> str | None:
    if not url or not url.startswith("http"):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=.8"})
        with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as r:
            body = r.read(500_000).decode("utf-8", "ignore")
        for pat in (
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        ):
            m = re.search(pat, body, re.I)
            if m:
                return m.group(1)
    except Exception:
        return None
    return None


def nested_source(source: dict[str, Any]) -> dict[str, Any]:
    value = source.get("source")
    return value if isinstance(value, dict) else {}


def mention_item(person: dict[str, Any], source: dict[str, Any], source_kind: str) -> dict[str, Any] | None:
    snapshot = role_snapshot(person)
    if not snapshot:
        return None
    hay = clean(" ".join(str(source.get(k) or "") for k in ("title", "headline", "summary", "standfirst", "meaning")))
    if not hay or not any(norm(alias) in norm(hay) for alias in person.get("aliases") or []):
        return None
    nested = nested_source(source)
    url = source.get("url") or nested.get("url")
    day = date_key(source.get("date") or source.get("observedAt") or source.get("updatedAt"))
    typ = type_for(hay)
    token = hashlib.sha1(f"{person['id']}|{day}|{hay}|{url or ''}".encode("utf-8")).hexdigest()[:10]
    tier = nested.get("tier") or source.get("tier") or "T1/T1B de verificat"
    return {
        "id": f"auto-{person['id']}-{day}-{token}",
        "personId": person["id"],
        "person": person["name"],
        "role": snapshot["role"],
        "institution": snapshot["institution"],
        "roleVerification": snapshot,
        "date": day,
        "type": typ,
        "signalKind": "STATEMENT_SIGNAL",
        "topic": source.get("programme") or source.get("tag") or person.get("institution"),
        "headline": clean(source.get("headline") or source.get("title"))[:220],
        "statement": clean(source.get("standfirst") or source.get("summary") or source.get("meaning"))[:500],
        "officialFact": "Semnalul este păstrat separat de efectul administrativ. Orice modificare de apel, termen, buget sau eligibilitate necesită document oficial T1/T1B.",
        "administrativeFact": {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True},
        "analysis": "Declarația este relevantă pentru monitorizare; impactul concret se stabilește numai după legarea de documentul sau apelul canonic aplicabil.",
        "watch": "Documentul oficial, ghidul, corrigendumul sau actul normativ care poate transforma semnalul într-un fapt operațional.",
        "audiences": ["Beneficiari", "Consultanți"],
        "sources": [{"label": f"{source_kind} — sursă observată", "url": url, "tier": tier}] if url else [],
        "autoGenerated": True,
    }


def main() -> int:
    registry = load(REGISTRY, {"people": [], "policy": {}})
    tracked_people = {
        p["id"]: p for p in registry.get("people") or []
        if p.get("active") and p.get("id")
    }
    current_verified_people = {
        person_id: person for person_id, person in tracked_people.items()
        if role_snapshot(person)
    }

    raw_seed = list(load(SEED, {"items": []}).get("items") or [])
    items = [dict(x) for x in raw_seed if x.get("personId") in current_verified_people]
    mipe = load(MIPE, {"items": []})
    decisions = load(DECISIONS, {"news": []})
    official = load(OFFICIAL, {"items": [], "sources": [], "quarantine": []})

    existing = {(x.get("personId"), norm(x.get("headline"))) for x in items}
    for person in current_verified_people.values():
        for source, kind in [
            *((x, "MIPE") for x in mipe.get("items") or []),
            *((x, "PARTENER.EU / sursă oficială") for x in decisions.get("news") or []),
        ]:
            row = mention_item(person, source, kind)
            if row and (row["personId"], norm(row["headline"])) not in existing:
                items.append(row)
                existing.add((row["personId"], norm(row["headline"])))

    official_rejected = 0
    for raw in official.get("items") or []:
        row = trusted_official_item(raw, tracked_people)
        if not row:
            official_rejected += 1
            continue
        key = (row["personId"], norm(row.get("headline")))
        if key in existing:
            continue
        items.append(row)
        existing.add(key)

    normalized: list[dict[str, Any]] = []
    for item in items:
        person = tracked_people.get(item.get("personId"))
        if not person:
            continue
        if item.get("officialIngested") is True:
            snapshot = persisted_role_snapshot(item.get("roleVerification"))
            if not snapshot:
                continue
            item["roleVerification"] = snapshot
            item["person"] = clean(item.get("person")) or person.get("name")
            item["role"] = snapshot["role"]
            item["institution"] = snapshot["institution"]
        else:
            current = current_verified_people.get(item.get("personId"))
            snapshot = role_snapshot(current) if current else None
            if not snapshot:
                continue
            item["person"] = current["name"]
            item["role"] = snapshot["role"]
            item["institution"] = snapshot["institution"]
            item["roleVerification"] = snapshot
        item["priority"] = int(item.get("priority") or person.get("priority") or 50)
        item["initials"] = item.get("initials") or "".join(part[0] for part in str(item.get("person") or "").split()[:2]).upper()
        item.setdefault("signalKind", "STATEMENT_SIGNAL")
        item.setdefault("administrativeFact", {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True})
        if not item.get("photoUrl"):
            for src in item.get("sources") or []:
                img = fetch_og_image(src.get("url") or "")
                if img:
                    item["photoUrl"] = img
                    break
        item["whyItMatters"] = item.get("analysis") or item.get("officialFact") or "Semnal relevant pentru monitorizare."
        normalized.append(item)

    dedup: dict[str, dict[str, Any]] = {}
    for item in normalized:
        key = clean(item.get("fingerprint")) or f"{item.get('personId')}|{norm(item.get('headline'))}|{date_key(item.get('date'))}"
        dedup[key] = item
    items = list(dedup.values())
    items.sort(key=lambda x: (date_key(x.get("date")), bool(x.get("officialIngested")), int(x.get("priority") or 0)), reverse=True)

    home: list[str] = []
    seen: set[str] = set()
    for x in items:
        if x["personId"] in seen:
            continue
        home.append(x["id"])
        seen.add(x["personId"])
        if len(home) == 3:
            break

    out = {
        "schemaVersion": 3,
        "asOf": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "mode": "AUTO",
        "policy": registry.get("policy") or {},
        "homeIds": home,
        "people": list(current_verified_people.values()),
        "items": items,
        "officialIngestion": {
            "generatedAt": official.get("generatedAt"),
            "ledgerSchemaVersion": official.get("schemaVersion"),
            "sourceCount": len(official.get("sources") or []),
            "ledgerItemCount": len(official.get("items") or []),
            "trustedItemCount": sum(1 for x in items if x.get("officialIngested") is True),
            "rejectedItemCount": official_rejected,
            "quarantineCount": len(official.get("quarantine") or []),
        },
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_PEOPLE_POLICY=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({
        "items": len(items),
        "homeIds": home,
        "verifiedPeople": len(current_verified_people),
        "trustedOfficialItems": out["officialIngestion"]["trustedItemCount"],
        "rejectedOfficialItems": official_rejected,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
