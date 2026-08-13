#!/usr/bin/env python3
"""Compile PARTENER.EU ingestion ledgers into one fail-closed intelligence index.

The index is the boundary between source collection and product intelligence.
It makes official evidence and planning signals searchable, but it never turns a
calendar row, page hash change, or discovered document into a published
deadline, budget, eligibility rule, score, or call status.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import tempfile
import urllib.parse
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE = ROOT / "ingest" / "state"
DEFAULT_OUTPUT = STATE / "intelligence_index.json"
DEFAULT_CONTRACT = ROOT / "ingest" / "data_plane_contract.json"
DEFAULT_SOURCE_REGISTRY = ROOT / "ingest" / "source_registry.json"
MATERIAL_FACT_CLASSES = [
    "deadline", "eligibility", "budget", "scoring", "beneficiaries",
    "material_call_status",
]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> Optional[dt.datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def load_json(path: pathlib.Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def atomic_json(path: pathlib.Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def stable_id(namespace: str, value: str) -> str:
    digest = hashlib.sha256(f"{namespace}|{value}".encode("utf-8")).hexdigest()[:24]
    return f"{namespace.lower()}-{digest}"


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def corpus_config(contract: Dict[str, Any], source_id: str) -> Dict[str, Any]:
    return (contract.get("corpora") or {}).get(source_id) or {}


def canonical_url(value: Any) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    parsed = urllib.parse.urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    port = f":{parsed.port}" if parsed.port else ""
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urllib.parse.urlunparse(("https", host + port, path, "", parsed.query, ""))


def freshness(observed_at: Any, reference: dt.datetime, max_age_hours: int) -> Dict[str, Any]:
    observed = parse_time(observed_at)
    if not observed:
        return {"status": "UNKNOWN", "ageHours": None, "maxAgeHours": max_age_hours}
    age = max(0.0, (reference - observed).total_seconds() / 3600)
    return {
        "status": "CURRENT" if age <= max_age_hours else "STALE",
        "ageHours": round(age, 2),
        "maxAgeHours": max_age_hours,
    }


def afir_records(
    state: Dict[str, Any], reference: dt.datetime, config: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    observed_at = state.get("generatedAt")
    sla = int(config.get("freshnessSlaHours") or 8)
    source = {
        "id": "AFIR_CORPUS",
        "tier": config.get("tier") or "T1",
        "domains": config.get("domains") or [],
        "programmes": config.get("programmes") or [],
        "sourceFamilies": config.get("sourceFamilies") or [],
        "dependencyScopes": config.get("dependencyScopes") or [],
        "status": state.get("status") or "UNKNOWN",
        "observedAt": observed_at,
        "freshness": freshness(observed_at, reference, sla),
        "itemCount": len(state.get("items") or []),
        "failClosed": True,
    }
    records = []
    for row in state.get("items") or []:
        url = canonical_url(row.get("url"))
        if not url or urllib.parse.urlparse(url).hostname != "afir.ro":
            continue
        material_candidate = bool(row.get("materialChangeCandidate"))
        content_type = str(row.get("contentType") or "").lower()
        path = urllib.parse.urlparse(url).path.lower()
        is_document = any(path.endswith(ext) for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ods", ".zip")) or (
            content_type and "html" not in content_type
        )
        records.append({
            "id": stable_id("afir", url),
            "sourceId": source["id"],
            "sourceTier": source["tier"],
            "recordType": "OFFICIAL_DOCUMENT" if is_document else "OFFICIAL_PAGE",
            "title": str(row.get("title") or pathlib.PurePosixPath(path).name)[:500],
            "programme": "AFIR / PS PAC 2023-2027",
            "canonicalUrl": url,
            "fingerprint": row.get("sha256"),
            "observedAt": observed_at,
            "freshness": source["freshness"]["status"],
            "textExtracted": bool(row.get("textExtracted")),
            "decisionUse": "OFFICIAL_EVIDENCE_INDEX",
            "materialChangeCandidate": material_candidate,
            "materialFactAction": "RESOLUTION_REQUIRED" if material_candidate else "NO_AUTO_PROMOTION",
            "publishMaterialFacts": False,
            "blockedFactClasses": MATERIAL_FACT_CLASSES,
            "provenance": [{"url": url, "tier": "T1", "label": "AFIR"}],
        })
    return source, records


def peo_calendar_records(
    state: Dict[str, Any], reference: dt.datetime, config: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    run = state.get("lastRun") or {}
    observed_at = run.get("observedAt")
    retrieval_url = canonical_url(state.get("retrievalSource"))
    sla = int(config.get("freshnessSlaHours") or 8)
    source = {
        "id": "PEO_CALENDAR",
        "tier": config.get("tier") or "T1B",
        "domains": config.get("domains") or [],
        "programmes": config.get("programmes") or [],
        "sourceFamilies": config.get("sourceFamilies") or [],
        "dependencyScopes": config.get("dependencyScopes") or [],
        "status": state.get("status") or "UNKNOWN",
        "observedAt": observed_at,
        "freshness": freshness(observed_at, reference, sla),
        "itemCount": len(state.get("items") or []),
        "canonicalContainer": canonical_url(state.get("canonicalContainer")),
        "retrievalSource": retrieval_url,
        "directMipeVerified": bool(state.get("directMipeVerified")),
        "failClosed": True,
    }
    records = []
    for row in state.get("items") or []:
        row_id = str(row.get("id") or "")
        title = str(row.get("title") or "").strip()
        if not row_id or not title:
            continue
        records.append({
            "id": stable_id("peo-calendar", row_id),
            "sourceId": source["id"],
            "sourceTier": source["tier"],
            "recordType": "PLANNED_CALL",
            "title": title[:500],
            "programme": str(row.get("programme") or "PEO"),
            "priority": row.get("priority"),
            "region": row.get("region"),
            "plannedLaunch": row.get("plannedLaunch"),
            "plannedClose": row.get("plannedClose"),
            "applicantsSignal": row.get("applicants"),
            "budgetSignal": row.get("budget"),
            "observedAt": observed_at,
            "freshness": source["freshness"]["status"],
            "decisionUse": "PLANNING_ONLY",
            "materialization": "NOT_YET_VERIFIED",
            "materialFactAction": "VERIFY_LAUNCH_AND_GUIDE_BEFORE_PUBLICATION",
            "publishMaterialFacts": False,
            "blockedFactClasses": MATERIAL_FACT_CLASSES,
            "provenance": ([{"url": retrieval_url, "tier": "T1B", "label": "OIR PECU Vest — copie instituțională"}] if retrieval_url else []),
        })
    return source, records


def mipe_records(
    state: Dict[str, Any], reference: dt.datetime, config: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    run = state.get("lastRun") or {}
    observed_at = run.get("observedAt")
    available = bool(run.get("sourceAvailable"))
    sla = int(config.get("freshnessSlaHours") or 8)
    source = {
        "id": "MIPE_CORPUS",
        "tier": config.get("tier") or "T1",
        "domains": config.get("domains") or [],
        "programmes": config.get("programmes") or [],
        "sourceFamilies": config.get("sourceFamilies") or [],
        "dependencyScopes": config.get("dependencyScopes") or [],
        "status": state.get("status") or "UNKNOWN",
        "observedAt": observed_at,
        "freshness": freshness(observed_at, reference, sla),
        "itemCount": len(state.get("items") or []),
        "sourceAvailable": available,
        "lastKnownGoodPreserved": "LAST_KNOWN_GOOD_PRESERVED" in str(state.get("status") or ""),
        "failClosed": True,
    }
    records = []
    for row in state.get("items") or []:
        url = canonical_url(row.get("url") or row.get("sourceUrl"))
        if not url or urllib.parse.urlparse(url).hostname != "mfe.gov.ro":
            continue
        records.append({
            "id": stable_id("mipe", url),
            "sourceId": source["id"],
            "sourceTier": source["tier"],
            "recordType": "OFFICIAL_MIPE_ITEM",
            "title": str(row.get("title") or row.get("headline") or url)[:500],
            "programme": row.get("programme") or "MIPE",
            "canonicalUrl": url,
            "fingerprint": row.get("sha256") or row.get("contentHash"),
            "observedAt": row.get("observedAt") or observed_at,
            "freshness": source["freshness"]["status"],
            "decisionUse": "OFFICIAL_EVIDENCE_INDEX" if available else "LAST_KNOWN_GOOD_DISCOVERY_ONLY",
            "materialFactAction": "EXTRACT_AND_RECONCILE_AUTHORITATIVE_EVIDENCE",
            "publishMaterialFacts": False,
            "blockedFactClasses": MATERIAL_FACT_CLASSES,
            "provenance": [{"url": url, "tier": "T1", "label": "MIPE"}],
        })
    return source, records


def registry_source(
    state: Dict[str, Any], reference: dt.datetime, config: Dict[str, Any]
) -> Dict[str, Any]:
    observed_at = state.get("observed_at")
    summary = state.get("summary") or {}
    sla = int(config.get("freshnessSlaHours") or 12)
    return {
        "id": "VERIFIED_SOURCE_REGISTRY",
        "tier": config.get("tier") or "MIXED_T1_T1B_T2",
        "domains": config.get("domains") or [],
        "programmes": config.get("programmes") or [],
        "sourceFamilies": config.get("sourceFamilies") or [],
        "dependencyScopes": config.get("dependencyScopes") or [],
        "status": "PASS" if not summary.get("fail") else "DEGRADED",
        "observedAt": observed_at,
        "freshness": freshness(observed_at, reference, sla),
        "itemCount": int(summary.get("total") or len(state.get("sources") or [])),
        "resolutionTasksRequired": int(summary.get("resolution_tasks_required") or 0),
        "failClosed": True,
    }


def state_contract_result(
    source_id: str,
    state: Dict[str, Any],
    config: Dict[str, Any],
    state_exists: bool,
) -> Dict[str, Any]:
    errors: List[str] = []
    if not state_exists:
        errors.append(f"{source_id}: state file missing")
    missing_root = [field for field in config.get("requiredRootFields") or [] if field not in state]
    if missing_root:
        errors.append(f"{source_id}: missing root fields {', '.join(missing_root)}")
    collection_key = "sources" if source_id == "VERIFIED_SOURCE_REGISTRY" else "items"
    rows = state.get(collection_key)
    invalid_items: List[Dict[str, Any]] = []
    if rows is not None and not isinstance(rows, list):
        errors.append(f"{source_id}: {collection_key} must be a list")
        rows = []
    for position, row in enumerate(rows or []):
        if not isinstance(row, dict):
            invalid_items.append({"position": position, "missingFields": ["<object>"]})
            continue
        missing = [field for field in config.get("requiredItemFields") or [] if field not in row]
        if missing:
            invalid_items.append({"position": position, "missingFields": missing})
    if invalid_items:
        errors.append(f"{source_id}: {len(invalid_items)} items violate the corpus contract")
    return {
        "status": "PASS" if not errors else "FAIL",
        "stateFile": config.get("stateFile"),
        "missingRootFields": missing_root,
        "invalidItemCount": len(invalid_items),
        "invalidItemSamples": invalid_items[:10],
        "errors": errors,
    }


def registry_families(source: Dict[str, Any]) -> List[str]:
    source_id = str(source.get("id") or "")
    source_class = str(source.get("class") or "").lower()
    families = []
    if source_id.startswith("SRC-MYSMIS"):
        families.append("MYSMIS")
    if source_id.startswith(("SRC-OIR", "SRC-OI-", "SRC-ADR")) or "intermediate_body" in source_class:
        families.append("OI_ADR")
    if "calendar" in source_class:
        families.append("CALENDARS")
    return sorted(set(families))


def registry_domains(source: Dict[str, Any], contract: Dict[str, Any]) -> List[str]:
    mapping = contract.get("programmeDomains") or {}
    domains = set()
    for programme in source.get("programmes") or []:
        domains.update(mapping.get(programme) or ["UNCLASSIFIED_PROGRAMME"])
    if "OI_ADR" in registry_families(source):
        domains.add("INTERMEDIATE_DELEGATED")
    if "CALENDARS" in registry_families(source):
        domains.add("PLANNING_CALENDAR")
    return sorted(domains)


def source_availability(source: Dict[str, Any]) -> str:
    contract_status = (source.get("contract") or {}).get("status")
    if contract_status == "FAIL":
        return "CONTRACT_FAIL"
    if source.get("sourceAvailable") is False:
        return "UNAVAILABLE_LAST_KNOWN_GOOD"
    freshness_status = (source.get("freshness") or {}).get("status")
    status = str(source.get("status") or "UNKNOWN").upper()
    if freshness_status == "STALE":
        return "STALE_LAST_KNOWN_GOOD"
    if freshness_status == "UNKNOWN":
        return "UNKNOWN"
    if status == "PASS" or status.startswith("OK_"):
        return "AVAILABLE"
    if "LAST_KNOWN_GOOD_PRESERVED" in status:
        return "UNAVAILABLE_LAST_KNOWN_GOOD"
    if status in {"FAIL", "MISSING"} or status.startswith("SOURCE_UNAVAILABLE"):
        return "UNAVAILABLE_LAST_KNOWN_GOOD"
    if status == "DEGRADED":
        return "DEGRADED_LAST_KNOWN_GOOD"
    return "UNKNOWN"


def dependency_gate(source: Dict[str, Any]) -> Dict[str, Any]:
    availability = source_availability(source)
    reasons = []
    if availability != "AVAILABLE":
        reasons.append(availability)
    if source.get("resolutionTaskRequired"):
        reasons.append("UNRESOLVED_SEMANTIC_CHANGE")
    if reasons:
        gate = "BLOCKED_SOURCE_DEPENDENCIES"
    elif source.get("planningOnly"):
        gate = "PLANNING_ONLY"
    elif not source.get("materialFactUse") or source.get("tier") in {"T2", "T3"}:
        gate = "DISCOVERY_ONLY"
    else:
        gate = "RECONCILIATION_REQUIRED"
    scopes = source.get("dependencyScopes") or source.get("programmes") or source.get("domains") or []
    return {
        "sourceId": source.get("id"),
        "availability": availability,
        "materialFactGate": gate,
        "affectedScopes": scopes,
        "blockingReasons": reasons,
        "lastKnownGoodPreserved": bool(source.get("lastKnownGoodPreserved", True)),
        "blocksUnrelatedSources": False,
        "publishMaterialFacts": False,
    }


def build_source_inventory(
    corpus_sources: List[Dict[str, Any]],
    source_registry: Dict[str, Any],
    registry_health: Dict[str, Any],
    contracts: Dict[str, Dict[str, Any]],
    contract: Dict[str, Any],
) -> List[Dict[str, Any]]:
    inventory = []
    for source in corpus_sources:
        row = dict(source)
        row.update({
            "kind": "CORPUS",
            "contract": contracts.get(str(source.get("id"))) or {"status": "FAIL"},
            "materialFactUse": source.get("id") in {"AFIR_CORPUS", "MIPE_CORPUS"},
            "planningOnly": source.get("id") == "PEO_CALENDAR",
            "lastKnownGoodPreserved": True,
            "resolutionTaskRequired": bool(source.get("resolutionTasksRequired")),
        })
        inventory.append(row)

    health_by_id = {str(row.get("id")): row for row in registry_health.get("sources") or []}
    registry_freshness = next(
        (row.get("freshness") for row in corpus_sources if row.get("id") == "VERIFIED_SOURCE_REGISTRY"),
        {"status": "UNKNOWN", "ageHours": None, "maxAgeHours": None},
    )
    observed_at = registry_health.get("observed_at")
    for definition in source_registry.get("sources") or []:
        source_id = str(definition.get("id") or "")
        if not source_id:
            continue
        health = health_by_id.get(source_id) or {}
        inventory.append({
            "id": source_id,
            "kind": "REGISTERED_OFFICIAL_SOURCE",
            "tier": definition.get("tier") or health.get("tier") or "UNKNOWN",
            "domains": registry_domains(definition, contract),
            "programmes": definition.get("programmes") or [],
            "sourceFamilies": registry_families(definition),
            "dependencyScopes": definition.get("programmes") or [],
            "sourceClass": definition.get("class"),
            "owner": definition.get("owner"),
            "canonicalUrl": canonical_url(definition.get("url")),
            "status": health.get("health") or "UNKNOWN",
            "observedAt": observed_at,
            "freshness": registry_freshness,
            "materialFactUse": bool(definition.get("material_fact_use")),
            "planningOnly": "calendar" in str(definition.get("class") or "").lower(),
            "resolutionTaskRequired": bool(health.get("resolution_task_required")),
            "lastKnownGoodPreserved": bool(
                health.get("semantic_sha256")
                or health.get("last_known_semantic_sha256")
                or health.get("health") == "PASS"
            ),
            "contract": {"status": "PASS", "errors": []},
        })
    inventory.sort(key=lambda row: str(row.get("id") or ""))
    return inventory


def build_data_plane(
    corpus_sources: List[Dict[str, Any]],
    states: Dict[str, Dict[str, Any]],
    state_dir: pathlib.Path,
    contract: Dict[str, Any],
    source_registry: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    contracts = {}
    errors: List[str] = []
    for source_id, config in (contract.get("corpora") or {}).items():
        state_path = state_dir / str(config.get("stateFile") or "")
        result = state_contract_result(
            source_id,
            states.get(source_id) or {},
            config,
            state_path.is_file(),
        )
        contracts[source_id] = result
        errors.extend(result["errors"])

    inventory = build_source_inventory(
        corpus_sources,
        source_registry,
        states.get("VERIFIED_SOURCE_REGISTRY") or {},
        contracts,
        contract,
    )
    inventory_ids = [str(row.get("id") or "") for row in inventory]
    if len(inventory_ids) != len(set(inventory_ids)):
        errors.append("source inventory ids are not unique")
    unclassified = [
        row["id"] for row in inventory
        if not row.get("tier") or not row.get("domains") or "UNCLASSIFIED_PROGRAMME" in row.get("domains", [])
    ]
    if unclassified:
        errors.append(f"unclassified sources: {', '.join(unclassified)}")

    gates = [dependency_gate(row) for row in inventory]
    gate_by_id = {row["sourceId"]: row for row in gates}
    tier_counts = Counter(str(row.get("tier") or "UNKNOWN") for row in inventory)
    domain_counts = Counter(domain for row in inventory for domain in row.get("domains") or ["UNKNOWN"])
    family_rows = []
    missing_families = []
    for family in contract.get("requiredSourceFamilies") or []:
        members = [row["id"] for row in inventory if family in (row.get("sourceFamilies") or [])]
        available = [source_id for source_id in members if gate_by_id[source_id]["availability"] == "AVAILABLE"]
        if not members:
            status = "MISSING"
            missing_families.append(family)
        elif available:
            status = "PRESENT_AVAILABLE"
        else:
            status = "PRESENT_DEGRADED"
        family_rows.append({"family": family, "status": status, "sourceIds": members, "availableSourceIds": available})
    if missing_families:
        errors.append(f"required source families missing: {', '.join(missing_families)}")

    freshness_rows = [{
        "sourceId": row.get("id"),
        **(row.get("freshness") or {"status": "UNKNOWN", "ageHours": None, "maxAgeHours": None}),
    } for row in inventory]
    current_count = sum(1 for row in freshness_rows if row.get("status") == "CURRENT")
    data_plane = {
        "contractId": contract.get("contractId"),
        "contractVersion": contract.get("schemaVersion"),
        "contract": {
            "status": "PASS" if not errors else "FAIL",
            "corpora": contracts,
            "errors": errors,
        },
        "freshness": {
            "status": "PASS" if current_count == len(freshness_rows) else "DEGRADED",
            "current": current_count,
            "total": len(freshness_rows),
            "slaBreaches": [row["sourceId"] for row in freshness_rows if row.get("status") != "CURRENT"],
            "sources": freshness_rows,
        },
        "coverage": {
            "status": "PASS" if not missing_families and not unclassified else "FAIL",
            "classifiedSourceCount": len(inventory) - len(unclassified),
            "sourceCount": len(inventory),
            "byTier": dict(sorted(tier_counts.items())),
            "byDomain": dict(sorted(domain_counts.items())),
            "requiredFamilies": family_rows,
            "missingRequiredFamilies": missing_families,
            "unclassifiedSourceIds": unclassified,
        },
        "sourceInventory": inventory,
        "dependencyIsolation": {
            "policy": "SOURCE_INCIDENTS_BLOCK_ONLY_DEPENDENT_FACT_SCOPES",
            "globalStop": bool(errors),
            "blockedSourceIds": [row["sourceId"] for row in gates if row["materialFactGate"] == "BLOCKED_SOURCE_DEPENDENCIES"],
            "unrelatedSourcesRemainUsable": not bool(errors),
            "gates": gates,
        },
    }
    return data_plane, errors


def deduplicate(records: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    output: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_urls = set()
    duplicates = 0
    for record in records:
        record_id = record.get("id")
        url = record.get("canonicalUrl")
        key_url = canonical_url(url) if url else None
        if not record_id or record_id in seen_ids or (key_url and key_url in seen_urls):
            duplicates += 1
            continue
        seen_ids.add(record_id)
        if key_url:
            seen_urls.add(key_url)
        output.append(record)
    output.sort(key=lambda row: (str(row.get("programme") or ""), str(row.get("title") or ""), str(row.get("id") or "")))
    return output, duplicates


def validate_contract(index: Dict[str, Any]) -> List[str]:
    errors = []
    ids = [row.get("id") for row in index.get("records") or []]
    if len(ids) != len(set(ids)):
        errors.append("record ids are not unique")
    for row in index.get("records") or []:
        if row.get("publishMaterialFacts") is not False:
            errors.append(f"{row.get('id')}: material fact publication is not fail-closed")
        if row.get("materialChangeCandidate") and row.get("materialFactAction") != "RESOLUTION_REQUIRED":
            errors.append(f"{row.get('id')}: material change lacks resolution gate")
        if not row.get("provenance"):
            errors.append(f"{row.get('id')}: provenance missing")
    if index.get("summary", {}).get("materialFactsAutopromoted") != 0:
        errors.append("materialFactsAutopromoted must remain zero")
    return errors


def compile_index(
    state_dir: pathlib.Path = STATE,
    reference: Optional[dt.datetime] = None,
    contract_path: pathlib.Path = DEFAULT_CONTRACT,
    source_registry_path: pathlib.Path = DEFAULT_SOURCE_REGISTRY,
) -> Dict[str, Any]:
    state_dir = pathlib.Path(state_dir)
    reference = (reference or utc_now()).astimezone(dt.timezone.utc)
    contract = load_json(pathlib.Path(contract_path), {})
    source_registry = load_json(pathlib.Path(source_registry_path), {"sources": []})
    afir = load_json(state_dir / "afir_corpus.json", {"status": "MISSING", "items": []})
    peo = load_json(state_dir / "peo_calendar_state.json", {"status": "MISSING", "items": []})
    mipe = load_json(state_dir / "mipe_state.json", {"status": "MISSING", "items": []})
    registry = load_json(state_dir / "source_registry_health.json", {"summary": {}, "sources": []})
    states = {
        "AFIR_CORPUS": afir,
        "PEO_CALENDAR": peo,
        "MIPE_CORPUS": mipe,
        "VERIFIED_SOURCE_REGISTRY": registry,
    }

    afir_source, afir_rows = afir_records(afir, reference, corpus_config(contract, "AFIR_CORPUS"))
    peo_source, peo_rows = peo_calendar_records(peo, reference, corpus_config(contract, "PEO_CALENDAR"))
    mipe_source, mipe_rows = mipe_records(mipe, reference, corpus_config(contract, "MIPE_CORPUS"))
    sources = [
        afir_source,
        peo_source,
        mipe_source,
        registry_source(registry, reference, corpus_config(contract, "VERIFIED_SOURCE_REGISTRY")),
    ]
    records, duplicates = deduplicate([*mipe_rows, *afir_rows, *peo_rows])
    data_plane, data_plane_errors = build_data_plane(
        sources, states, state_dir, contract, source_registry
    )

    record_types = Counter(str(row.get("recordType") or "UNKNOWN") for row in records)
    programmes = Counter(str(row.get("programme") or "UNKNOWN") for row in records)
    resolution_count = sum(1 for row in records if row.get("materialFactAction") == "RESOLUTION_REQUIRED")
    resolution_count += sources[-1]["resolutionTasksRequired"]
    stale_sources = data_plane["freshness"]["slaBreaches"]
    gates = {row["sourceId"]: row for row in data_plane["dependencyIsolation"]["gates"]}
    unavailable_t1 = [
        row["id"] for row in data_plane["sourceInventory"]
        if row.get("tier") == "T1" and gates[row["id"]]["availability"] != "AVAILABLE"
    ]
    readiness = "READY_FOR_DISCOVERY_ONLY"
    if data_plane_errors:
        readiness = "BLOCKED_CONTRACT_FAIL_CLOSED"
    elif unavailable_t1 or stale_sources or resolution_count:
        readiness = "DEGRADED_FAIL_CLOSED"

    index = {
        "schemaVersion": 2,
        "generatedAt": iso_z(reference),
        "readiness": readiness,
        "policy": {
            "purpose": "unified-search-and-evidence-index",
            "materialFactsAutopromoted": False,
            "planningSignalsAreCalls": False,
            "hashChangesAutoPublish": False,
            "tierPrecedence": ["T1", "T1B", "T2", "T3"],
        },
        "sources": sources,
        "records": records,
        "dataPlane": data_plane,
        "summary": {
            "sourceCount": data_plane["coverage"]["sourceCount"],
            "corpusCount": len(sources),
            "recordCount": len(records),
            "duplicatesRemoved": duplicates,
            "recordTypes": dict(sorted(record_types.items())),
            "programmes": dict(sorted(programmes.items())),
            "staleOrUnknownSources": stale_sources,
            "unavailableT1Sources": unavailable_t1,
            "resolutionTasksRequired": resolution_count,
            "materialFactsAutopromoted": 0,
        },
    }
    errors = [*validate_contract(index), *data_plane_errors]
    index["contract"] = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    input_digest = canonical_digest({
        "contract": contract,
        "sourceRegistry": source_registry,
        "states": states,
    })
    output_digest = canonical_digest(index)
    index["dataPlane"]["replay"] = {
        "status": "DIGEST_READY",
        "algorithm": "sha256-canonical-json",
        "referenceTime": iso_z(reference),
        "inputDigest": input_digest,
        "outputDigest": output_digest,
    }
    return index


def compile_with_replay(
    state_dir: pathlib.Path = STATE,
    reference: Optional[dt.datetime] = None,
    contract_path: pathlib.Path = DEFAULT_CONTRACT,
    source_registry_path: pathlib.Path = DEFAULT_SOURCE_REGISTRY,
) -> Dict[str, Any]:
    reference = (reference or utc_now()).astimezone(dt.timezone.utc)
    first = compile_index(state_dir, reference, contract_path, source_registry_path)
    second = compile_index(state_dir, reference, contract_path, source_registry_path)
    first_digest = canonical_digest(first)
    second_digest = canonical_digest(second)
    replay_pass = first_digest == second_digest
    first["dataPlane"]["replay"].update({
        "status": "PASS" if replay_pass else "FAIL",
        "firstPassDigest": first_digest,
        "secondPassDigest": second_digest,
        "byteEquivalent": replay_pass,
    })
    if not replay_pass:
        error = "deterministic replay mismatch"
        first["contract"]["status"] = "FAIL"
        first["contract"]["errors"].append(error)
        first["dataPlane"]["contract"]["status"] = "FAIL"
        first["dataPlane"]["contract"]["errors"].append(error)
        first["readiness"] = "BLOCKED_CONTRACT_FAIL_CLOSED"
    return first


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate without writing the index")
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state-dir", type=pathlib.Path, default=STATE)
    parser.add_argument("--contract", type=pathlib.Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--source-registry", type=pathlib.Path, default=DEFAULT_SOURCE_REGISTRY)
    parser.add_argument("--as-of", help="ISO-8601 reference time for deterministic tests")
    args = parser.parse_args()
    reference = parse_time(args.as_of) if args.as_of else None
    if args.as_of and not reference:
        parser.error("--as-of must be an ISO-8601 timestamp")
    index = compile_with_replay(
        state_dir=args.state_dir,
        reference=reference,
        contract_path=args.contract,
        source_registry_path=args.source_registry,
    )
    if not args.check:
        atomic_json(args.output, index)
    print(json.dumps({
        "readiness": index["readiness"],
        **index["summary"],
        "coverage": index["dataPlane"]["coverage"]["status"],
        "freshness": index["dataPlane"]["freshness"]["status"],
        "replay": index["dataPlane"]["replay"]["status"],
        "contract": index["contract"]["status"],
    }, ensure_ascii=False, indent=2))
    return 0 if index["contract"]["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
