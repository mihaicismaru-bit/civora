#!/usr/bin/env python3
"""Fail-closed validation for the VÂLCEA CLAR durable monitor registry."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "editorial" / "monitor_registry.json"
NEWS_SOURCES = ROOT / "editorial" / "news_sources.json"
MANUAL_SOURCES = ROOT / "editorial" / "manual_watch_sources.json"

ALLOWED_MONITOR_STATUSES = {
    "ACTIVE",
    "ACTIVE_REVERIFY",
    "ACTIVE_EXISTING",
    "DEGRADED_SOURCE",
    "RESOLVED",
    "PUBLISHED_AND_CLOSED",
    "INVALIDATED_WITH_REASON",
    "SUPERSEDED_WITH_LINK",
}
TERMINAL = {
    "RESOLVED",
    "PUBLISHED_AND_CLOSED",
    "INVALIDATED_WITH_REASON",
    "SUPERSEDED_WITH_LINK",
}
REQUIRED_RECOVERED = {
    "health-sju-valcea-recruitment-watch",
    "health-brezoi-hospital-watch",
    "health-horezu-hospital-watch",
    "council-watch-valcea",
    "real-estate-development-radar",
    "real-estate-market-watch",
    "olanesti-infrastructure-dossier",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    errors: list[str] = []
    data = load(REGISTRY)
    news = load(NEWS_SOURCES)
    manual = load(MANUAL_SOURCES)

    if data.get("schema_version") != "1.0":
        errors.append("monitor_registry schema_version must be 1.0")
    if data.get("instance_id") != "valcea":
        errors.append("monitor_registry instance_id must be valcea")
    if data.get("execution_owner") != "CIVORA_SITE_ENGINE":
        errors.append("CIVORA must own monitor execution")
    if data.get("state_owner") != "GITHUB_REPOSITORY":
        errors.append("GitHub repository must own monitor state")

    policy = data.get("policy") or {}
    required_policy = {
        "monitor_is_not_story": True,
        "monitor_or_lead_public_projection": False,
        "source_change_is_not_material_fact": True,
        "normal_story_ready_gate_required_for_publication": True,
        "recap_or_edition_expiry_may_delete_monitor": False,
        "homepage_rebuild_may_delete_monitor": False,
        "monitor_may_close_only_with_explicit_resolution": True,
        "unverified_recovered_details_must_remain_fail_closed": True,
        "chatgpt_scheduler_allowed": False,
        "chatgpt_state_owner_allowed": False,
        "paid_dependency_required": False,
    }
    for key, value in required_policy.items():
        if policy.get(key) is not value:
            errors.append(f"policy.{key} must be {value!r}")

    declared_required = set(data.get("required_recovered_monitor_ids") or [])
    if declared_required != REQUIRED_RECOVERED:
        errors.append("required_recovered_monitor_ids drifted from recovery contract")

    news_ids = {str(row.get("id")) for row in news.get("sources") or []}
    manual_ids = {str(row.get("id")) for row in manual.get("sources") or []}
    monitors = data.get("monitors") or []
    monitor_ids = [str(row.get("id") or "") for row in monitors]
    if len(monitor_ids) != len(set(monitor_ids)):
        errors.append("monitor ids must be unique")
    missing = REQUIRED_RECOVERED - set(monitor_ids)
    if missing:
        errors.append("missing recovered monitors: " + ", ".join(sorted(missing)))

    lead_ids: set[str] = set()
    for monitor in monitors:
        mid = str(monitor.get("id") or "")
        if not mid:
            errors.append("monitor without id")
            continue
        status = monitor.get("status")
        if status not in ALLOWED_MONITOR_STATUSES:
            errors.append(f"{mid}: invalid status {status!r}")
        if not monitor.get("label") or not monitor.get("purpose"):
            errors.append(f"{mid}: label and purpose are required")
        if not monitor.get("close_when"):
            errors.append(f"{mid}: explicit close_when is required")
        if status in TERMINAL and "reason" not in monitor and status in {"INVALIDATED_WITH_REASON", "SUPERSEDED_WITH_LINK"}:
            errors.append(f"{mid}: terminal state {status} requires reason/link metadata")

        bindings = monitor.get("source_bindings") or []
        if not bindings:
            errors.append(f"{mid}: at least one source binding is required")
        binding_ids: set[str] = set()
        for binding in bindings:
            bid = str(binding.get("id") or "")
            btype = binding.get("ref_type")
            if not bid:
                errors.append(f"{mid}: source binding without id")
                continue
            if bid in binding_ids:
                errors.append(f"{mid}: duplicate source binding id {bid}")
            binding_ids.add(bid)
            if btype == "news_source_id":
                if bid not in news_ids:
                    errors.append(f"{mid}: unknown news_source_id {bid}")
            elif btype == "manual_watch_source_id":
                if bid not in manual_ids:
                    errors.append(f"{mid}: unknown manual_watch_source_id {bid}")
            elif btype == "investigation_file":
                path = ROOT.parent / str(binding.get("path") or "")
                if not path.is_file():
                    errors.append(f"{mid}: missing investigation file {binding.get('path')}")
            elif btype == "url":
                url = str(binding.get("url") or "")
                parsed = urlparse(url)
                if parsed.scheme != "https" or not parsed.netloc:
                    errors.append(f"{mid}: direct source {bid} must use an https URL")
                if binding.get("probe") is True and not isinstance(binding.get("match_terms") or [], list):
                    errors.append(f"{mid}: probed source {bid} match_terms must be a list")
            else:
                errors.append(f"{mid}: unsupported source binding type {btype!r}")

        for lead in monitor.get("recovered_leads") or []:
            lid = str(lead.get("id") or "")
            if not lid:
                errors.append(f"{mid}: recovered lead without id")
                continue
            if lid in lead_ids:
                errors.append(f"duplicate recovered lead id {lid}")
            lead_ids.add(lid)
            if lead.get("public_projection") is not False:
                errors.append(f"{mid}/{lid}: recovered lead public_projection must be false")
            verification = str(lead.get("verification_status") or "")
            if not verification:
                errors.append(f"{mid}/{lid}: verification_status is required")
            if not lead.get("recovery_note"):
                errors.append(f"{mid}/{lid}: recovery_note is required")

    # Guard the exact remembered threads so future refactors cannot silently drop them.
    required_leads = {
        "sju-bulk-recruitment-working-note",
        "brezoi-palliative-care-project",
        "brezoi-microbiology-project",
        "horezu-ambulatory-extension",
        "rm-valcea-hcl159-2026-musiclover-public-money",
        "calimanesti-council-decisions-stream",
        "ferdinand-19",
        "doru-popian-2-5-4a",
        "intrarea-crizantemei-1",
        "dealul-malului-11g",
    }
    lost_leads = required_leads - lead_ids
    if lost_leads:
        errors.append("missing recovered lead(s): " + ", ".join(sorted(lost_leads)))

    if errors:
        print("VÂLCEA CLAR monitor registry: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "VÂLCEA CLAR monitor registry: PASS "
        f"({len(monitors)} monitors, {len(lead_ids)} recovered leads, durable fail-closed persistence)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
