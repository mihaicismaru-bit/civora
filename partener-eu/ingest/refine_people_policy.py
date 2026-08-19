#!/usr/bin/env python3
"""Refine 'Ce spun decidenții' into a homepage-only, fresh, official-source product.

The canonical builder is the trust boundary. This stage never re-imports raw
official-ledger rows; it only selects from builder-validated items.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
PEOPLE = ROOT / "partener-eu" / "ingest" / "state" / "people_policy.json"
SOURCE_REGISTRY = ROOT / "partener-eu" / "ingest" / "state" / "people_policy_source_registry.json"
OUT_JS = ROOT / "partener-eu" / "web" / "people-policy-data.js"
FRESH_DAYS = 60


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def item_date(item: dict[str, Any]) -> dt.date | None:
    value = str(item.get("date") or "")[:10]
    try:
        return dt.date.fromisoformat(value)
    except Exception:
        return None


def official_hosts(source_registry: dict[str, Any]) -> set[str]:
    hosts: set[str] = set()
    for source in source_registry.get("sources") or []:
        if not source.get("enabled", True):
            continue
        tier = str(source.get("tier") or "")
        if not tier.startswith("T1"):
            continue
        hosts.update(str(x).lower() for x in source.get("allowedHosts") or [] if x)
    return hosts


def direct_official(item: dict[str, Any], allowed_hosts: set[str]) -> bool:
    for source in item.get("sources") or []:
        url = str(source.get("url") or "")
        host = (urlparse(url).hostname or "").lower()
        tier = str(source.get("tier") or "").upper()
        if host in allowed_hosts and tier.startswith("T1"):
            return True
    return False


def fail_closed_signal(item: dict[str, Any]) -> bool:
    fact = item.get("administrativeFact")
    return (
        item.get("signalKind") == "STATEMENT_SIGNAL"
        and isinstance(fact, dict)
        and fact.get("status") == "UNCONFIRMED_FROM_SIGNAL"
        and fact.get("failClosed") is True
    )


def main() -> int:
    people = load(PEOPLE, {"items": [], "policy": {}})
    source_registry = load(SOURCE_REGISTRY, {"sources": []})
    allowed_hosts = official_hosts(source_registry)
    items = list(people.get("items") or [])
    items.sort(key=lambda x: (str(x.get("date") or ""), bool(x.get("officialIngested")), int(x.get("priority") or 0)), reverse=True)

    today = dt.datetime.now(dt.timezone.utc).date()
    candidates = []
    for item in items:
        d = item_date(item)
        if not d or (today - d).days < 0 or (today - d).days > FRESH_DAYS:
            continue
        if not direct_official(item, allowed_hosts):
            continue
        if not fail_closed_signal(item):
            continue
        if not item.get("headline") or not item.get("officialFact"):
            continue
        candidates.append(item)

    candidates.sort(key=lambda x: (bool(x.get("officialIngested")), str(x.get("date") or ""), int(x.get("priority") or 0)), reverse=True)
    home: list[str] = []
    seen_actor: set[str] = set()
    max_items = int((people.get("policy") or {}).get("homepageMaxItems") or 3)
    for item in candidates:
        actor = str(item.get("personId") or "")
        if not actor or actor in seen_actor:
            continue
        home.append(str(item["id"]))
        seen_actor.add(actor)
        if len(home) >= max_items:
            break

    policy = people.setdefault("policy", {})
    policy.update({
        "homepageOnly": True,
        "officialSourceIngestion": True,
        "directOfficialHomepageOnly": True,
        "homeFreshnessDays": FRESH_DAYS,
        "hideWhenNoFreshOfficialSignals": True,
        "statementIsNotAdministrativeFact": True,
        "officialEffectRequiresT1Evidence": True,
        "rawOfficialLedgerNeverBypassesCanonicalBuilder": True,
    })
    people["items"] = items
    people["homeIds"] = home
    summary = people.setdefault("officialIngestion", {})
    summary["homeEligibleCount"] = len(candidates)
    summary["configuredOfficialHosts"] = len(allowed_hosts)

    PEOPLE.write_text(json.dumps(people, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_PEOPLE_POLICY=" + json.dumps(people, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({"items": len(items), "home": len(home), "officialCandidates": len(candidates)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
