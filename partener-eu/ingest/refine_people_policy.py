#!/usr/bin/env python3
"""Refine 'Ce spun decidenții' into a homepage-only, fresh, official-source product."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
PEOPLE = ROOT / "partener-eu/ingest/state/people_policy.json"
OFFICIAL = ROOT / "partener-eu/ingest/state/people_policy_official_sources.json"
OUT_JS = ROOT / "partener-eu/web/people-policy-data.js"

DIRECT_HOSTS = {
    "mfe.gov.ro", "www.mfe.gov.ro", "ms.gov.ro", "www.ms.gov.ro",
    "research.gov.ro", "www.research.gov.ro", "adr.gov.ro", "www.adr.gov.ro",
    "fed.mai.gov.ro", "gov.ro", "www.gov.ro", "legislatie.just.ro",
    "ec.europa.eu", "commission.europa.eu",
}
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


def direct_official(item: dict[str, Any]) -> bool:
    for source in item.get("sources") or []:
        url = str(source.get("url") or "")
        host = (urlparse(url).hostname or "").lower()
        tier = str(source.get("tier") or "").upper()
        if host in DIRECT_HOSTS and (tier.startswith("T1") or tier.startswith("T1B") or "OFFICIAL" in tier):
            return True
    return False


def main() -> int:
    people = load(PEOPLE, {"items": [], "policy": {}})
    official = load(OFFICIAL, {"items": [], "policy": {}})
    by_id = {str(x.get("id")): x for x in people.get("items") or [] if x.get("id")}
    for item in official.get("items") or []:
        if item.get("id"):
            by_id[str(item["id"])] = item
    items = list(by_id.values())
    items.sort(key=lambda x: (str(x.get("date") or ""), bool(x.get("officialIngested")), int(x.get("priority") or 0)), reverse=True)

    today = dt.datetime.now(dt.timezone.utc).date()
    candidates = []
    for item in items:
        d = item_date(item)
        if not d or (today - d).days < 0 or (today - d).days > FRESH_DAYS:
            continue
        if not direct_official(item):
            continue
        if not item.get("headline") or not item.get("officialFact"):
            continue
        candidates.append(item)

    # Prefer signals ingested directly from official institutional pages, then corroborated legacy seeds.
    candidates.sort(key=lambda x: (bool(x.get("officialIngested")), str(x.get("date") or ""), int(x.get("priority") or 0)), reverse=True)
    home: list[str] = []
    seen_actor: set[str] = set()
    max_items = int((people.get("policy") or {}).get("homepageMaxItems") or 3)
    for item in candidates:
        actor = str(item.get("personId") or item.get("person") or item.get("institution") or "")
        if not actor or actor in seen_actor:
            continue
        home.append(str(item["id"])); seen_actor.add(actor)
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
    })
    people["items"] = items
    people["homeIds"] = home
    people["officialIngestion"] = {
        "generatedAt": official.get("generatedAt"),
        "sourceCount": len(official.get("sources") or []),
        "acceptedItemCount": len(official.get("items") or []),
        "homeEligibleCount": len(candidates),
    }
    PEOPLE.write_text(json.dumps(people, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_PEOPLE_POLICY=" + json.dumps(people, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({"items": len(items), "home": len(home), "officialCandidates": len(candidates)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
