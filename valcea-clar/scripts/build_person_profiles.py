#!/usr/bin/env python3
"""Build VÂLCEA CLAR public-person profiles with fail-closed evidence gates.

This engine is deliberately incremental. A resolved public identity may have a
minimal profile while historical research continues. Sensitive adverse facts do
not become public simply because a name appears in a court result or a private
editorial document.

Private evidence (for example an ONRC extract supplied to the newsroom) may be
read from a local manifest, but only opaque receipts are retained in the public
artifact. Raw private content and claims backed only by private evidence never
cross the public projection boundary.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "editorial" / "person_profile_policy.json"
SEEDS = ROOT / "editorial" / "person_profile_seeds.json"
OVERRIDES = ROOT / "editorial" / "person_profile_overrides.json"
OUT = ROOT / "site" / "runtime" / "people.json"
QUEUE = ROOT / "editorial" / "person_source_discovery_queue.json"
PRIVATE_ENV = "VALCEA_CLAR_PRIVATE_EVIDENCE_MANIFEST"

ALLOWED_LEGAL = {
    "PLAINTIFF", "DEFENDANT_CIVIL", "PETITIONER", "RESPONDENT", "SUSPECT",
    "DEFENDANT_CRIMINAL", "INDICTED", "CONVICTED_NOT_FINAL", "CONVICTED_FINAL",
    "ACQUITTED", "CASE_DISMISSED", "PROCEEDINGS_TERMINATED",
    "IMPRISONMENT_SERVED_VERIFIED", "UNKNOWN",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def slugify(value: str) -> str:
    return norm(value).replace(" ", "-") or "persoana"


def source_domain(url: str) -> str:
    return (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")


def source_index(seed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in seed.get("public_sources") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if url:
            index[url] = row
    return index


def public_source_urls(row: dict[str, Any]) -> list[str]:
    return [str(url).strip() for url in row.get("source_urls") or [] if str(url).strip().startswith(("http://", "https://"))]


def validate_source_binding(row: dict[str, Any], sources: dict[str, dict[str, Any]], *, label: str) -> None:
    urls = public_source_urls(row)
    if not urls:
        raise ValueError(f"{label}: public fact requires source_urls")
    unknown = [url for url in urls if url not in sources]
    if unknown:
        raise ValueError(f"{label}: source_urls must be registered public sources: {unknown}")


def legal_event_public(event: dict[str, Any], sources: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    status = str(event.get("legal_status") or "UNKNOWN").upper()
    role = str(event.get("role") or "").upper()
    if status not in ALLOWED_LEGAL:
        return False, "invalid_legal_status"
    if status == "UNKNOWN":
        return False, "unknown_legal_status"
    if not role:
        return False, "missing_legal_role"
    urls = public_source_urls(event)
    if not urls:
        return False, "missing_public_source"
    if any(url not in sources for url in urls):
        return False, "unregistered_public_source"

    if status == "IMPRISONMENT_SERVED_VERIFIED":
        if event.get("final_legal_basis") is not True:
            return False, "imprisonment_requires_final_legal_basis"
        tiers = {str(sources[url].get("tier") or "") for url in urls}
        classes = {str(sources[url].get("source_class") or "") for url in urls}
        authoritative = "T1" in tiers and bool(classes & {"official_court", "official_gazette", "public_authority"})
        if not authoritative:
            return False, "imprisonment_requires_authoritative_source"
    return True, "PASS"


def relationship_public(event: dict[str, Any], sources: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    if event.get("public_interest_relevance") is not True:
        return False, "relationship_not_public_interest"
    if event.get("publicly_documented") is not True:
        return False, "relationship_not_publicly_documented"
    if not str(event.get("relation") or "").strip() or not str(event.get("person_name") or "").strip():
        return False, "relationship_missing_identity"
    urls = public_source_urls(event)
    if not urls or any(url not in sources for url in urls):
        return False, "relationship_missing_registered_public_source"
    return True, "PASS"


def company_public(event: dict[str, Any], sources: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    role = str(event.get("role") or "").strip()
    entity = str(event.get("organization") or event.get("company") or "").strip()
    if not role or not entity:
        return False, "company_relation_missing_role_or_entity"
    urls = public_source_urls(event)
    if not urls or any(url not in sources for url in urls):
        return False, "company_relation_missing_registered_public_source"
    if event.get("beneficial_owner") is True and event.get("beneficial_owner_explicitly_documented") is not True:
        return False, "beneficial_owner_inference_forbidden"
    if event.get("shareholder") is True and event.get("shareholding_explicitly_documented") is not True:
        return False, "shareholding_inference_forbidden"
    return True, "PASS"


def timeline_date(row: dict[str, Any]) -> str:
    for key in ("date", "from", "start_date", "decision_date"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return "9999"


def build_timeline(profile: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role in profile.get("roles") or []:
        rows.append({
            "date": role.get("from"),
            "end_date": role.get("to"),
            "type": "role",
            "label": f"{role.get('title')} — {role.get('organization')}",
            "source_urls": role.get("source_urls") or [],
        })
    for election in profile.get("election_history") or []:
        rows.append({
            "date": election.get("date"),
            "type": "election",
            "label": election.get("label") or "Participare electorală",
            "source_urls": election.get("source_urls") or [],
        })
    for event in profile.get("legal_cases") or []:
        rows.append({
            "date": event.get("date") or event.get("registered_at"),
            "type": "legal_case",
            "label": event.get("public_label") or f"Dosar {event.get('case_number') or ''}".strip(),
            "legal_status": event.get("legal_status"),
            "role": event.get("role"),
            "source_urls": event.get("source_urls") or [],
        })
    return sorted(rows, key=lambda row: (timeline_date(row), str(row.get("type") or ""), str(row.get("label") or "")))


def deep_set(target: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in str(path).split(".") if part]
    if not parts:
        raise ValueError("empty override path")
    node: dict[str, Any] = target
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = copy.deepcopy(value)


def deep_get(target: dict[str, Any], path: str) -> Any:
    node: Any = target
    for part in [p for p in str(path).split(".") if p]:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def deep_delete(target: dict[str, Any], path: str) -> None:
    parts = [part for part in str(path).split(".") if part]
    if not parts:
        return
    node: Any = target
    for part in parts[:-1]:
        if not isinstance(node, dict):
            return
        node = node.get(part)
    if isinstance(node, dict):
        node.pop(parts[-1], None)


def apply_override(profile: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    if not override:
        return profile
    note = str(override.get("audit_note") or "").strip()
    if not note:
        raise ValueError(f"{profile['id']}: nonempty manual override requires audit_note")
    for path, value in (override.get("set") or {}).items():
        deep_set(profile, path, value)
    for path, values in (override.get("append") or {}).items():
        existing = deep_get(profile, path)
        if existing is None:
            deep_set(profile, path, [])
            existing = deep_get(profile, path)
        if not isinstance(existing, list):
            raise ValueError(f"{profile['id']}: append override target is not list: {path}")
        for value in values if isinstance(values, list) else [values]:
            if value not in existing:
                existing.append(copy.deepcopy(value))
    for path in override.get("suppress") or []:
        deep_delete(profile, str(path))
    profile["manual_override"] = {
        "applied": True,
        "audit_note": note,
        "updated_at": override.get("updated_at"),
    }
    return profile


def load_private_records(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    p = Path(path).expanduser().resolve()
    doc = json.loads(p.read_text(encoding="utf-8"))
    rows = doc.get("records") or []
    if not isinstance(rows, list):
        raise ValueError("private evidence manifest records must be a list")
    return [row for row in rows if isinstance(row, dict)]


def private_receipts(person_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for row in records:
        if str(row.get("person_id") or "") != person_id:
            continue
        receipt = {
            "opaque_evidence_id": str(row.get("opaque_evidence_id") or "").strip(),
            "sha256": str(row.get("sha256") or "").strip(),
            "evidence_class": str(row.get("evidence_class") or "").strip(),
            "verification_state": str(row.get("verification_state") or "UNVERIFIED").strip(),
        }
        if not receipt["opaque_evidence_id"] or not re.fullmatch(r"[a-fA-F0-9]{64}", receipt["sha256"]):
            raise ValueError(f"{person_id}: private evidence receipt requires opaque id and sha256")
        receipts.append(receipt)
    return receipts


def public_summary(seed: dict[str, Any]) -> str:
    name = str(seed.get("canonical_name") or "").strip()
    roles = seed.get("roles") or []
    current = next((row for row in roles if str(row.get("status") or "").startswith("current")), None)
    basis = str(seed.get("public_interest_basis") or "").strip()
    if current:
        lead = f"{name} este documentat de VÂLCEA CLAR ca {str(current.get('title') or '').lower()} în cadrul {current.get('organization')}."
    else:
        lead = f"{name} are un profil public VÂLCEA CLAR construit din apariții și documente verificabile."
    return " ".join(part for part in (lead, basis) if part)


def discovery_tasks(seed: dict[str, Any]) -> list[dict[str, Any]]:
    name = str(seed.get("canonical_name") or "").strip()
    aliases = [name] + [str(a).strip() for a in seed.get("aliases") or [] if str(a).strip()]
    query = " OR ".join(f'"{alias}"' for alias in aliases)
    types = set(seed.get("profile_types") or [])
    tasks = [
        {"source_class": "official_court", "domains": ["portal.just.ro"], "query": query, "target": "case history and procedural status", "publication_authority": "NONE"},
        {"source_class": "official_gazette", "domains": ["monitoruloficial.ro"], "query": query, "target": "appointments, dismissals and historical official acts", "publication_authority": "NONE"},
        {"source_class": "public_authority_archives", "domains": ["gov.ro", "senat.ro", "cdep.ro", "cjvalcea.ro", "primariavl.ro", "primariabrezoi.ro"], "query": query, "target": "roles, CVs, decisions and archive mentions", "publication_authority": "NONE"},
        {"source_class": "press_archives", "domains": [], "query": query, "target": "historical context and contemporaneous reporting", "publication_authority": "NONE"},
    ]
    if types & {"politician", "public_official"}:
        tasks.extend([
            {"source_class": "elections", "domains": ["roaep.ro", "prezenta.roaep.ro", "bec.ro"], "query": query, "target": "candidacies and election results", "publication_authority": "NONE"},
            {"source_class": "integrity_and_declarations", "domains": ["integritate.eu", "old-declaratii.integritate.eu"], "query": query, "target": "historical public declarations and integrity findings", "publication_authority": "NONE"},
        ])
    return tasks


def build_profile(seed: dict[str, Any], override: dict[str, Any], private_records: list[dict[str, Any]]) -> dict[str, Any]:
    person_id = str(seed.get("id") or "").strip()
    name = str(seed.get("canonical_name") or "").strip()
    identity = seed.get("identity") if isinstance(seed.get("identity"), dict) else {}
    if not person_id or not name:
        raise ValueError("person seed missing id/canonical_name")
    if identity.get("status") != "RESOLVED":
        raise ValueError(f"{person_id}: ambiguous/unresolved identity cannot become public profile")
    sources = source_index(seed)
    if not sources:
        raise ValueError(f"{person_id}: at least one public source is required")

    roles = copy.deepcopy(seed.get("roles") or [])
    for idx, row in enumerate(roles):
        validate_source_binding(row, sources, label=f"{person_id}.roles[{idx}]")

    elections = copy.deepcopy(seed.get("election_history") or [])
    accepted_elections = []
    holds = []
    for idx, row in enumerate(elections):
        try:
            validate_source_binding(row, sources, label=f"{person_id}.election_history[{idx}]")
            accepted_elections.append(row)
        except ValueError as exc:
            holds.append({"kind": "election_history", "index": idx, "reason": str(exc)})

    legal = []
    for idx, event in enumerate(copy.deepcopy(seed.get("legal_cases") or [])):
        ok, reason = legal_event_public(event, sources)
        if ok:
            legal.append(event)
        else:
            holds.append({"kind": "legal_case", "index": idx, "reason": reason})

    relationships = []
    for idx, event in enumerate(copy.deepcopy(seed.get("relationships") or [])):
        ok, reason = relationship_public(event, sources)
        if ok:
            relationships.append(event)
        else:
            holds.append({"kind": "relationship", "index": idx, "reason": reason})

    companies = []
    raw_companies = seed.get("public_companies_and_organizations") or seed.get("companies") or []
    for idx, event in enumerate(copy.deepcopy(raw_companies)):
        ok, reason = company_public(event, sources)
        if ok:
            companies.append(event)
        else:
            holds.append({"kind": "company_relation", "index": idx, "reason": reason})

    profile = {
        "id": person_id,
        "name": name,
        "aliases": list(dict.fromkeys([str(a).strip() for a in seed.get("aliases") or [] if str(a).strip()])),
        "path": f"/oameni/{slugify(person_id)}/",
        "publication_status": "public",
        "identity": copy.deepcopy(identity),
        "profile_types": copy.deepcopy(seed.get("profile_types") or ["public_personality"]),
        "public_interest_basis": seed.get("public_interest_basis"),
        "summary": public_summary(seed),
        "roles": roles,
        "election_history": accepted_elections,
        "legal_cases": legal,
        "public_companies_and_organizations": companies,
        "relationships": relationships,
        "story_refs": copy.deepcopy(seed.get("story_refs") or []),
        "public_sources": list(sources.values()),
        "research_holds": holds,
        "private_evidence_receipts": private_receipts(person_id, private_records),
        "source_discovery": {"status": "QUEUED", "oldest_first_backfill": True, "tasks": discovery_tasks(seed)},
    }
    profile["timeline"] = build_timeline(profile)
    profile = apply_override(profile, override)
    profile["timeline"] = build_timeline(profile)
    return profile


def build_document(policy: dict[str, Any], seeds: dict[str, Any], overrides: dict[str, Any], private_records: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    people = seeds.get("people") or []
    if not isinstance(people, list):
        raise ValueError("person seeds people must be a list")
    override_map = overrides.get("overrides") or {}
    ids: set[str] = set()
    profiles = []
    for seed in people:
        if not isinstance(seed, dict):
            continue
        pid = str(seed.get("id") or "").strip()
        if pid in ids:
            raise ValueError(f"duplicate person id: {pid}")
        ids.add(pid)
        profiles.append(build_profile(seed, override_map.get(pid) or {}, private_records))
    profiles.sort(key=lambda row: str(row.get("name") or "").casefold())
    queue = {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR People Intelligence Source Discovery Queue",
        "publication_authority": "NONE",
        "profile_count": len(profiles),
        "tasks": [{"person_id": p["id"], "canonical_name": p["name"], "identity_status": p["identity"].get("status"), "tasks": p["source_discovery"]["tasks"]} for p in profiles],
        "policy": {"candidate_source_never_equals_verified_fact": True, "historical_discovery_is_incremental": True, "sensitive_claims_require_dedicated_gate": True},
    }
    doc = {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR People Intelligence",
        "profile_count": len(profiles),
        "profiles": profiles,
        "policy": {"public_route_root": policy.get("public_route_root", "/oameni/"), "ambiguous_identity_fail_closed": True, "legal_case_existence_never_implies_guilt": True, "private_evidence_public_projection_forbidden": True, "manual_override_applied_last": True, "historical_discovery_enabled": True},
    }
    return doc, queue


def self_test() -> int:
    public = {"name": "Official", "url": "https://official.example/p", "tier": "T1", "source_class": "public_authority"}
    seed = {
        "id": "ana-test", "canonical_name": "Ana Test", "aliases": [], "profile_types": ["politician"], "public_interest_basis": "Test",
        "identity": {"status": "RESOLVED", "disambiguators": ["Test City"]},
        "roles": [{"title": "Primar", "organization": "Test City", "from": "2024", "to": null, "status": "current_as_of_source", "source_urls": [public["url"]]}],
        "election_history": [], "legal_cases": [], "relationships": [], "public_companies_and_organizations": [], "story_refs": ["story-test"], "public_sources": [public],
    }
    fake_hash = hashlib.sha256(b"private onrc bytes").hexdigest()
    private = [{"person_id": "ana-test", "opaque_evidence_id": "onrc-ana-001", "sha256": fake_hash, "evidence_class": "ONRC_EXTRACT", "verification_state": "REVIEWED_INTERNAL", "raw_content": "THIS MUST NEVER LEAK", "claims": [{"text": "private-only claim"}]}]
    p = build_profile(seed, {}, private)
    serialized = json.dumps(p, ensure_ascii=False)
    assert "THIS MUST NEVER LEAK" not in serialized
    assert "private-only claim" not in serialized
    assert p["private_evidence_receipts"][0]["sha256"] == fake_hash

    unresolved = copy.deepcopy(seed)
    unresolved["identity"]["status"] = "AMBIGUOUS"
    try:
        build_profile(unresolved, {}, [])
    except ValueError:
        pass
    else:
        raise AssertionError("ambiguous identity must fail closed")

    sources = source_index(seed)
    case = {"case_number": "1/2/2026", "role": "DEFENDANT", "legal_status": "UNKNOWN", "source_urls": [public["url"]]}
    assert legal_event_public(case, sources)[0] is False

    prison = {"case_number": "1/2/2026", "role": "DEFENDANT_CRIMINAL", "legal_status": "IMPRISONMENT_SERVED_VERIFIED", "final_legal_basis": False, "source_urls": [public["url"]]}
    assert legal_event_public(prison, sources) == (False, "imprisonment_requires_final_legal_basis")
    prison["final_legal_basis"] = True
    assert legal_event_public(prison, sources)[0] is True

    override = {"audit_note": "Corecție editorială test", "set": {"summary": "Rezumat controlat editorial."}, "append": {"profile_types": ["manual_test"]}, "suppress": ["relationships"]}
    p2 = build_profile(seed, override, [])
    assert p2["summary"] == "Rezumat controlat editorial."
    assert "manual_test" in p2["profile_types"]
    assert "relationships" not in p2
    print("VÂLCEA CLAR People Intelligence self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--private-evidence-manifest", default=os.getenv(PRIVATE_ENV))
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    policy = load(POLICY)
    seeds = load(SEEDS)
    overrides = load(OVERRIDES)
    private_records = load_private_records(args.private_evidence_manifest)
    doc, queue = build_document(policy, seeds, overrides, private_records)

    if args.check:
        if doc["profile_count"] < 1:
            raise SystemExit("People Intelligence requires at least one resolved public seed")
        raw = json.dumps(doc, ensure_ascii=False)
        if "raw_content" in raw:
            raise SystemExit("private raw content leaked into public People Intelligence")
        print(json.dumps({"status": "PASS", "profiles": doc["profile_count"], "private_receipts": sum(len(p["private_evidence_receipts"]) for p in doc["profiles"])}, ensure_ascii=False))
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "profiles": doc["profile_count"], "output": str(OUT.relative_to(ROOT)), "research_queue": str(QUEUE.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
