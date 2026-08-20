#!/usr/bin/env python3
"""Build automated 'Ce spun decidenții' data for PARTENER.EU.

The builder is the trust boundary for person-level signals. It combines durable
direct-official observations, explicitly evidenced synthetic observations and
historical seeds that already carry a verified role-at-observation snapshot.
Statements remain signals until separately corroborated by T1/T1B administrative
evidence. Generic listing/homepage rows never become person signals.
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
SOURCE_REGISTRY = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_source_registry.json"
MIPE = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
DECISIONS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JSON = ROOT / "partener-eu" / "ingest" / "state" / "people_policy.json"
OUT_JS = ROOT / "partener-eu" / "web" / "people-policy-data.js"
UA = "PARTENER.EU-PeoplePolicy/3.2 (+https://partener.eu)"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.I)

FUNDING_EVIDENCE_TERMS = (
    "fonduri europene", "finantare", "finanțare", "pnrr", "program", "apel",
    "grant", "buget", "coeziune", "investitii", "investiții", "mysmis",
    "proiect", "contract", "plati", "plăți", "aloc", "ajutor de stat",
)
SIGNAL_EVIDENCE_TERMS = (
    "a declarat", "a anuntat", "a anunțat", "a precizat", "a spus", "a afirmat",
    "a explicat", "a subliniat", "a mentionat", "a menționat", "a transmis",
    "a aratat", "a arătat", "a adaugat", "a adăugat", "anunta", "anunță",
    "declara", "declară", "precizeaza", "precizează", "spune", "afirma", "afirmă",
    "explica", "explică", "subliniaza", "subliniază", "propune", "prelung", "acceler",
    "negocier", "aprobat", "adoptat", "semnat", "lans", "prioritate", "decizie",
)
DIRECT_QUOTE_SIGNAL_CUE = "DIRECT_QUOTE_ATTRIBUTION"
DIRECT_QUOTE_ROLE_TERMS = (
    "ministr", "președ", "presed", "director", "secretar de stat",
    "comisar", "premier", "prim-ministr",
)
DIRECT_QUOTE_CLOSERS = {"„": "”", "“": "”", "«": "»", '"': '"'}


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def clean(s: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(s or ""))).strip()


def norm(s: Any) -> str:
    return clean(s).lower().translate(str.maketrans("ăâîșşțţ", "aaisstt"))


def canonical_source_url(value: Any) -> str:
    return clean(value).split("#", 1)[0].rstrip("/")


def configured_listing_roots() -> set[str]:
    registry = load(SOURCE_REGISTRY, {"sources": []})
    return {
        canonical_source_url(source.get("url"))
        for source in registry.get("sources") or []
        if source.get("enabled", True) and canonical_source_url(source.get("url"))
    }


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


def fail_closed_signal(item: Any) -> bool:
    if not isinstance(item, dict) or item.get("signalKind") != "STATEMENT_SIGNAL":
        return False
    admin = item.get("administrativeFact")
    return (
        isinstance(admin, dict)
        and admin.get("status") == "UNCONFIRMED_FROM_SIGNAL"
        and admin.get("failClosed") is True
    )


def alias_present(text: Any, alias: Any) -> bool:
    """Match a person alias only as a complete folded token sequence."""
    value = norm(text)
    needle = norm(alias)
    if not needle:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", value) is not None


def actor_alias(person: dict[str, Any], text: str) -> str | None:
    aliases = [clean(x) for x in person.get("aliases") or [] if clean(x)]
    name = clean(person.get("name"))
    if name:
        aliases.append(name)
    for alias in sorted(set(aliases), key=len, reverse=True):
        if alias_present(text, alias):
            return alias
    return None


def direct_quote_statement_evidence(person: dict[str, Any], statement: str) -> dict[str, str] | None:
    """Re-derive attributed direct-quote evidence at the canonical trust boundary."""
    value = clean(statement)
    folded = norm(value)
    aliases = [clean(alias) for alias in person.get("aliases") or [] if clean(alias)]
    name = clean(person.get("name"))
    if name:
        aliases.append(name)
    for alias in sorted(set(aliases), key=len, reverse=True):
        needle = norm(alias)
        if not needle:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])"
        for match in re.finditer(pattern, folded):
            colon = folded.find(":", match.end(), min(len(folded), match.end() + 180))
            if colon < 0:
                continue
            attribution = folded[match.end():colon]
            if not any(norm(term) in attribution for term in DIRECT_QUOTE_ROLE_TERMS):
                continue
            tail = value[colon + 1:colon + 951]
            stripped = tail.lstrip()
            leading = len(tail) - len(stripped)
            if not stripped or stripped[0] not in DIRECT_QUOTE_CLOSERS:
                continue
            opener = stripped[0]
            quote_start = leading + 1
            quote_end = tail.find(DIRECT_QUOTE_CLOSERS[opener], quote_start)
            if quote_end < 0:
                continue
            quote = clean(tail[quote_start:quote_end])
            if len(quote) < 45 or len(quote.split()) < 8:
                continue
            funding = next((term for term in FUNDING_EVIDENCE_TERMS if norm(term) in norm(quote)), None)
            if funding:
                return {
                    "actorAlias": alias,
                    "fundingCue": funding,
                    "evidenceMode": "ACTOR_ROLE_COLON_QUOTE",
                }
    return None


def article_statement_evidence(
    item: dict[str, Any], person: dict[str, Any], source_url: str, snapshot: dict[str, Any]
) -> dict[str, Any] | None:
    """Derive strict article-level evidence from an official ledger observation.

    The collector's `statement` is extracted from the fetched article, while the
    source snapshot binds that article to a content hash. We require the actor,
    a statement/announcement cue and funding context in the compact evidence
    window. This deliberately rejects generic homepages/listings.
    """
    headline = clean(item.get("headline"))
    statement = clean(item.get("statement"))
    if not statement:
        return None
    window = clean(f"{headline}. {statement}")
    alias = actor_alias(person, window)
    if not alias:
        return None
    folded = norm(window)
    statement_folded = norm(statement)
    direct_quote = direct_quote_statement_evidence(person, statement)
    if direct_quote:
        signal = DIRECT_QUOTE_SIGNAL_CUE
        funding = direct_quote["fundingCue"]
        evidence_mode = direct_quote["evidenceMode"]
        alias = direct_quote["actorAlias"]
    else:
        signal = next((x for x in SIGNAL_EVIDENCE_TERMS if norm(x) in statement_folded or norm(x) in folded), None)
        funding = next((x for x in FUNDING_EVIDENCE_TERMS if norm(x) in folded), None)
        evidence_mode = "ACTOR_SPEECH_CUE"
        if not signal or not funding:
            return None
    content_hash = clean(snapshot.get("contentHash"))
    observed_at = clean(snapshot.get("observedAt"))
    if not SHA256_RE.fullmatch(content_hash) or not observed_at:
        return None
    return {
        "status": "VERIFIED_ARTICLE_STATEMENT",
        "actorAlias": alias,
        "articleUrl": source_url,
        "observedAt": observed_at,
        "contentHash": content_hash,
        "statement": statement[:600],
        "signalCue": signal,
        "fundingCue": funding,
        "evidenceMode": evidence_mode,
    }


def persisted_statement_evidence(
    value: Any, person: dict[str, Any], source_url: str, snapshot: dict[str, Any]
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("status") != "VERIFIED_ARTICLE_STATEMENT":
        return None
    article_url = clean(value.get("articleUrl"))
    content_hash = clean(value.get("contentHash"))
    observed_at = clean(value.get("observedAt"))
    statement = clean(value.get("statement"))
    if article_url != source_url or content_hash != clean(snapshot.get("contentHash")):
        return None
    if observed_at != clean(snapshot.get("observedAt")) or not statement:
        return None
    if not actor_alias(person, statement):
        return None
    signal_cue = clean(value.get("signalCue"))
    if signal_cue == DIRECT_QUOTE_SIGNAL_CUE:
        direct_quote = direct_quote_statement_evidence(person, statement)
        if not direct_quote:
            return None
        funding_cue = direct_quote["fundingCue"]
        evidence_mode = direct_quote["evidenceMode"]
        actor = direct_quote["actorAlias"]
    else:
        if not any(norm(x) in norm(statement) for x in SIGNAL_EVIDENCE_TERMS):
            return None
        combined = clean(f"{value.get('fundingCue')} {statement}")
        if not any(norm(x) in norm(combined) for x in FUNDING_EVIDENCE_TERMS):
            return None
        funding_cue = clean(value.get("fundingCue"))
        evidence_mode = clean(value.get("evidenceMode")) or "ACTOR_SPEECH_CUE"
        actor = clean(value.get("actorAlias"))
    return {
        "status": "VERIFIED_ARTICLE_STATEMENT",
        "actorAlias": actor,
        "articleUrl": article_url,
        "observedAt": observed_at,
        "contentHash": content_hash,
        "statement": statement[:600],
        "signalCue": signal_cue,
        "fundingCue": funding_cue,
        "evidenceMode": evidence_mode,
    }


def trusted_official_item(item: Any, tracked_people: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Validate one durable official-ledger observation fail-closed."""
    if not isinstance(item, dict) or item.get("officialIngested") is not True:
        return None
    person_id = clean(item.get("personId"))
    person = tracked_people.get(person_id)
    if not person or not fail_closed_signal(item):
        return None
    role = persisted_role_snapshot(item.get("roleVerification"))
    if not role or date_key(item.get("date")) == "1970-01-01":
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
    if canonical_source_url(source_url) in configured_listing_roots():
        return None
    snapshot = item.get("sourceSnapshot")
    if not isinstance(snapshot, dict) or clean(snapshot.get("url")) != source_url:
        return None
    if not clean(snapshot.get("sourceId")) or not clean(snapshot.get("publisher")):
        return None
    if not clean(snapshot.get("tier")).startswith("T1") or not clean(snapshot.get("observedAt")):
        return None
    if not SHA256_RE.fullmatch(clean(snapshot.get("contentHash"))):
        return None
    if not SHA256_RE.fullmatch(clean(item.get("fingerprint"))):
        return None
    evidence = article_statement_evidence(item, person, source_url, snapshot)
    if not evidence:
        return None
    canonical = item.get("canonicalLink")
    if not isinstance(canonical, dict) or canonical.get("status") not in {"UNRESOLVED", "MATCHED_EXPLICIT_CODE"}:
        return None
    if canonical.get("status") == "MATCHED_EXPLICIT_CODE" and not (clean(canonical.get("callId")) and clean(canonical.get("code"))):
        return None
    out = dict(item)
    out["roleVerification"] = role
    out["personId"] = person_id
    out["statementEvidence"] = evidence
    return out


def trusted_seed_item(item: Any, tracked_people: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Accept historical/manual seeds only with role-at-observation proof.

    A current registry role is never backfilled onto a historical statement.
    Legacy seeds without their own T1/T1B role snapshot remain excluded until
    they are explicitly re-verified.
    """
    if not isinstance(item, dict):
        return None
    person_id = clean(item.get("personId"))
    person = tracked_people.get(person_id)
    if not person or date_key(item.get("date")) == "1970-01-01":
        return None
    role = persisted_role_snapshot(item.get("roleVerification"))
    if not role or not fail_closed_signal(item):
        return None
    if not all(clean(item.get(k)) for k in ("headline", "statement", "analysis", "watch", "topic")):
        return None
    sources = item.get("sources")
    if not isinstance(sources, list) or not sources:
        return None
    if not any(isinstance(src, dict) and clean(src.get("url")).startswith("https://") for src in sources):
        return None
    out = dict(item)
    out["personId"] = person_id
    out["person"] = clean(item.get("person")) or clean(person.get("name"))
    out["roleVerification"] = role
    out["role"] = role["role"]
    out["institution"] = role["institution"]
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
    """Convert an upstream row only when it already carries article evidence.

    MIPE/decision-product listing rows are useful for calls/news, but they are not
    person statements. This path therefore requires an explicit role-at-observation
    snapshot, source snapshot and article-statement evidence from upstream.
    """
    role = persisted_role_snapshot(source.get("roleVerification"))
    source_snapshot = source.get("sourceSnapshot")
    if not role or not isinstance(source_snapshot, dict):
        return None
    nested = nested_source(source)
    url = clean(source.get("url") or nested.get("url"))
    tier = clean(nested.get("tier") or source.get("tier"))
    if not url.startswith("https://") or not tier.startswith("T1"):
        return None
    if clean(source_snapshot.get("url")) != url or not SHA256_RE.fullmatch(clean(source_snapshot.get("contentHash"))):
        return None
    evidence = persisted_statement_evidence(source.get("statementEvidence"), person, url, source_snapshot)
    if not evidence:
        return None
    hay = clean(f"{source.get('title')} {source.get('headline')} {evidence.get('statement')}")
    if not actor_alias(person, hay):
        return None
    day = date_key(source.get("date") or source.get("observedAt") or source.get("updatedAt"))
    if day == "1970-01-01":
        return None
    headline = clean(source.get("headline") or source.get("title"))[:220]
    if not headline:
        return None
    fingerprint = hashlib.sha256(
        f"{person['id']}|{url}|{source_snapshot.get('contentHash')}".encode("utf-8")
    ).hexdigest()
    return {
        "id": f"auto-{person['id']}-{day}-{fingerprint[:10]}",
        "personId": person["id"],
        "person": person["name"],
        "role": role["role"],
        "institution": role["institution"],
        "roleVerification": role,
        "date": day,
        "type": type_for(hay),
        "signalKind": "STATEMENT_SIGNAL",
        "topic": source.get("programme") or source.get("tag") or role["institution"],
        "headline": headline,
        "statement": evidence["statement"],
        "statementEvidence": evidence,
        "officialFact": "Semnalul este păstrat separat de efectul administrativ. Orice modificare de apel, termen, buget sau eligibilitate necesită document oficial T1/T1B.",
        "administrativeFact": {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True},
        "analysis": "Declarația este relevantă pentru monitorizare; impactul concret se stabilește numai după legarea de documentul sau apelul canonic aplicabil.",
        "watch": "Documentul oficial, ghidul, corrigendumul sau actul normativ care poate transforma semnalul într-un fapt operațional.",
        "audiences": ["Beneficiari", "Consultanți"],
        "sources": [{"label": f"{source_kind} — sursă observată", "url": url, "tier": tier}],
        "sourceSnapshot": dict(source_snapshot),
        "fingerprint": fingerprint,
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
    items: list[dict[str, Any]] = []
    seed_rejected = 0
    for raw in raw_seed:
        row = trusted_seed_item(raw, tracked_people)
        if row:
            items.append(row)
        else:
            seed_rejected += 1

    mipe = load(MIPE, {"items": []})
    decisions = load(DECISIONS, {"news": []})
    official = load(OFFICIAL, {"items": [], "sources": [], "quarantine": []})

    existing = {(x.get("personId"), norm(x.get("headline"))) for x in items}
    synthetic_rejected = 0
    synthetic_trusted = 0
    for person in tracked_people.values():
        for source, kind in [
            *((x, "MIPE") for x in mipe.get("items") or []),
            *((x, "PARTENER.EU / sursă oficială") for x in decisions.get("news") or []),
        ]:
            row = mention_item(person, source, kind)
            if not row:
                if actor_alias(person, clean(f"{source.get('title')} {source.get('headline')} {source.get('summary')} {source.get('standfirst')} {source.get('meaning')}")):
                    synthetic_rejected += 1
                continue
            key = (row["personId"], norm(row["headline"]))
            if key not in existing:
                items.append(row)
                existing.add(key)
                synthetic_trusted += 1

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
        if not person or not fail_closed_signal(item):
            continue
        snapshot = persisted_role_snapshot(item.get("roleVerification"))
        if not snapshot:
            continue
        item["roleVerification"] = snapshot
        item["person"] = clean(item.get("person")) or clean(person.get("name"))
        item["role"] = snapshot["role"]
        item["institution"] = snapshot["institution"]
        item["priority"] = int(item.get("priority") or person.get("priority") or 50)
        item["initials"] = item.get("initials") or "".join(part[0] for part in str(item.get("person") or "").split()[:2]).upper()
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

    policy = dict(registry.get("policy") or {})
    policy.update({
        "genericListingRowsCannotBecomePersonSignals": True,
        "articleStatementEvidenceRequiredForOfficialSignals": True,
        "attributedDirectQuoteEvidenceSupported": True,
        "directQuoteRequiresActorRoleColonAndFundingInQuote": True,
        "historicalSignalsRequireRoleAtObservation": True,
        "actorAliasesRequireTokenBoundaries": True,
        "configuredListingRootsExcludedFromProjection": True,
    })
    out = {
        "schemaVersion": 3,
        "asOf": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "mode": "AUTO",
        "policy": policy,
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
            "trustedSeedCount": sum(1 for x in items if x.get("id") in {s.get("id") for s in raw_seed}),
            "rejectedLegacySeedCount": seed_rejected,
            "trustedSyntheticCount": synthetic_trusted,
            "rejectedSyntheticMentions": synthetic_rejected,
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
        "rejectedLegacySeeds": seed_rejected,
        "trustedSynthetic": synthetic_trusted,
        "rejectedSyntheticMentions": synthetic_rejected,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())