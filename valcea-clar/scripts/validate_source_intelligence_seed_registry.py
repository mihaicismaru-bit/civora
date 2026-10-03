#!/usr/bin/env python3
"""Validate the VÂLCEA CLAR source-intelligence expansion seed contract."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "editorial" / "source_intelligence_seed_registry.json"
DISCOVERY_STATE = ROOT / "editorial" / "source_intelligence_discovery_state.json"
ALLOWED_TIERS = {"T1", "T1B", "T2", "T3"}
REQUIRED_CAMPAIGN_FAMILIES = {
    "LOCAL_PRESS", "UAT", "PUBLIC_RECORD", "PUBLIC_INSTITUTIONS", "COMPANY",
    "VENUE", "CULTURE", "PROFESSIONAL", "PUBLIC_FIGURE", "COMMUNITY",
}


def fail(message: str) -> None:
    raise SystemExit("SOURCE INTELLIGENCE seed validation FAIL: " + message)


def coverage_scorecard(targets: dict) -> dict:
    """Report delivered coverage separately from the declared contract.

    Discovery candidates are not equivalent to monitored URLs.  Until the
    engine owns an active-URL ledger, the 2,000-URL canon target is explicitly
    unmeasured instead of being implied by a passing schema validation.
    """
    source_target = int(targets.get("phase_1_sources", 0))
    url_target = int(targets.get("phase_1_monitored_urls", 0))
    if not DISCOVERY_STATE.is_file():
        return {
            "status": "UNMEASURED",
            "phase_1_source_target": source_target,
            "realized_seed_sources": None,
            "source_completion_percent": None,
            "phase_1_monitored_url_target": url_target,
            "active_monitored_urls": None,
            "monitored_url_measurement": "MISSING_DISCOVERY_STATE",
        }

    try:
        state = json.loads(DISCOVERY_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        fail("source intelligence discovery state is unreadable")
    if state.get("instance_id") != "valcea":
        fail("discovery state instance_id must be valcea")

    realized_sources = int(state.get("seed_count") or 0)
    observations = [row for row in state.get("observations") or [] if isinstance(row, dict)]
    discovered_urls = {
        str(candidate.get("url") or "").strip()
        for row in observations
        for candidate in row.get("candidates") or []
        if isinstance(candidate, dict) and str(candidate.get("url") or "").strip()
    }
    degraded_sources = sum(1 for row in observations if row.get("status") != "PASS")
    source_target_met = source_target > 0 and realized_sources >= source_target
    return {
        "status": "PHASE_1_SOURCE_TARGET_MET" if source_target_met else "BELOW_PHASE_1",
        "phase_1_source_target": source_target,
        "realized_seed_sources": realized_sources,
        "source_completion_percent": round(100 * realized_sources / source_target, 1) if source_target else None,
        "observed_sources": len(observations),
        "degraded_sources": degraded_sources,
        "phase_1_monitored_url_target": url_target,
        "active_monitored_urls": None,
        "discovered_unique_candidate_urls": len(discovered_urls),
        "monitored_url_measurement": "MISSING_CANONICAL_ACTIVE_URL_LEDGER",
    }


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
        "contract_status": "PASS",
        "coverage": coverage_scorecard(targets),
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
