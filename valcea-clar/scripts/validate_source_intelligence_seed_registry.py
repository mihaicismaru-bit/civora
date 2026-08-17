#!/usr/bin/env python3
"""Validate the VÂLCEA CLAR source-intelligence expansion seed contract."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "editorial" / "source_intelligence_seed_registry.json"
ALLOWED_TIERS = {"T1", "T1B", "T2", "T3"}
REQUIRED_CAMPAIGN_FAMILIES = {
    "LOCAL_PRESS", "UAT", "PUBLIC_RECORD", "PUBLIC_INSTITUTIONS", "COMPANY",
    "VENUE", "CULTURE", "PROFESSIONAL", "PUBLIC_FIGURE", "COMMUNITY",
}


def fail(message: str) -> None:
    raise SystemExit("SOURCE INTELLIGENCE seed validation FAIL: " + message)


def main() -> int:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if data.get("instance_id") != "valcea":
        fail("instance_id must be valcea")
    defaults = data.get("defaults") or {}
    if defaults.get("signal_only") is not True:
        fail("seed defaults must remain signal_only")
    if defaults.get("public_projection") is not False or defaults.get("auto_publication") is not False:
        fail("seed defaults may never authorize publication")
    policy = data.get("policy") or {}
    if policy.get("zero_auto_publication") is not True:
        fail("zero_auto_publication must remain true")
    if policy.get("t2_t3_require_higher_authority_confirmation") is not True:
        fail("T2/T3 escalation rule missing")
    targets = data.get("phase_targets") or {}
    if int(targets.get("phase_1_sources", 0)) < 250:
        fail("Phase 1 source target regressed below 250")
    if int(targets.get("phase_1_monitored_urls", 0)) < 2000:
        fail("Phase 1 URL target regressed below 2000")

    ids, urls = set(), set()
    sources = data.get("seed_sources") or []
    for raw in sources:
        if not isinstance(raw, list) or len(raw) != 6:
            fail(f"invalid compact seed row: {raw!r}")
        sid, publisher, url, tier, family, sensitive = raw
        if not sid or sid in ids:
            fail(f"invalid/duplicate seed id: {sid!r}")
        ids.add(sid)
        if not publisher or not family:
            fail(f"{sid}: publisher/family missing")
        if tier not in ALLOWED_TIERS:
            fail(f"{sid}: invalid tier")
        parsed = urlsplit(str(url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            fail(f"{sid}: invalid URL")
        if url in urls:
            fail(f"duplicate seed URL: {url}")
        urls.add(url)
        if not isinstance(sensitive, bool):
            fail(f"{sid}: sensitive flag must be boolean")

    campaigns = data.get("campaigns") or []
    families = {str(c.get("family") or "") for c in campaigns}
    missing = REQUIRED_CAMPAIGN_FAMILIES - families
    if missing:
        fail("missing campaign families: " + ", ".join(sorted(missing)))
    total_target = 0
    for campaign in campaigns:
        target = int(campaign.get("target_sources", 0))
        if target <= 0:
            fail(f"{campaign.get('id')}: target_sources must be positive")
        total_target += target
        policy_name = str(campaign.get("publication_policy") or "")
        if not policy_name or policy_name == "AUTO_PUBLISH":
            fail(f"{campaign.get('id')}: unsafe publication policy")
    if total_target < 250:
        fail("campaign target coverage below Phase 1")

    print(json.dumps({
        "status": "PASS",
        "seed_sources": len(sources),
        "campaigns": len(campaigns),
        "campaign_target_total": total_target,
        "phase_1_sources": targets["phase_1_sources"],
        "phase_1_monitored_urls": targets["phase_1_monitored_urls"],
        "publication_authority": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
