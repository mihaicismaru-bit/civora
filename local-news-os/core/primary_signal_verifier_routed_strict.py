#!/usr/bin/env python3
"""Production primary verifier with boundary-safe routing and dedicated targets.

This adapter preserves the ranked strict corroboration gate and adds only a
config-driven primary-target registry. It grants no Fact Kernel or publication
authority.

Official primary listings sometimes carry the only trustworthy publication date
in the link label while the linked document omits machine-readable date metadata.
This adapter may recover that explicit terminal listing date, but only from a
strict unambiguous pattern, and records the provenance so the strict freshness
gate remains fail-closed rather than silently accepting undated evidence.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CORE = Path(__file__).resolve().parent
ROOT = CORE.parents[1]
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import primary_signal_verifier as base  # noqa: E402
import primary_signal_verifier_ranked as ranked  # noqa: E402
import primary_signal_verifier_strict as strict  # noqa: E402
import signal_radar as radar  # noqa: E402
import signal_routing_contract as routing  # noqa: E402

LEGACY_FETCH_PRIMARY_CANDIDATE = base.fetch_primary_candidate
LEGACY_VERIFY_TASK = base.verify_task
LISTING_DATE_DMY = re.compile(r"\((\d{1,2})[./](\d{1,2})[./](\d{4})\)\s*$")
LISTING_DATE_ISO = re.compile(r"\((\d{4})-(\d{2})-(\d{2})\)\s*$")


def listing_label_published_at(label: str, tz: ZoneInfo) -> datetime | None:
    """Return a date only when an official listing label ends in an explicit date."""
    clean = radar.clean(label)
    match = LISTING_DATE_DMY.search(clean)
    if match:
        day, month, year = (int(value) for value in match.groups())
    else:
        match = LISTING_DATE_ISO.search(clean)
        if not match:
            return None
        year, month, day = (int(value) for value in match.groups())
    try:
        return datetime(year, month, day, tzinfo=tz)
    except ValueError:
        return None


def listing_date_aware_fetch_primary_candidate(
    url: str,
    fallback_title: str,
    tz: ZoneInfo,
) -> dict[str, Any] | None:
    doc = LEGACY_FETCH_PRIMARY_CANDIDATE(url, fallback_title, tz)
    if doc is None:
        return None
    if doc.get("published_at"):
        doc.setdefault("published_at_source", "primary_document_metadata")
        return doc

    published = listing_label_published_at(fallback_title, tz)
    if published is not None:
        doc["published_at"] = published.isoformat(timespec="seconds")
        doc["published_at_source"] = "official_listing_label"
        doc["listing_label"] = radar.clean(fallback_title)[:300]
    return doc


def listing_date_aware_verify_task(
    task: dict[str, Any],
    corpora: dict[tuple[str, str], dict[str, Any]],
    tz: ZoneInfo,
) -> dict[str, Any]:
    result = LEGACY_VERIFY_TASK(task, corpora, tz)
    evidence = result.get("primary_evidence")
    if result.get("status") != "PRIMARY_MATCH_FOUND" or not isinstance(evidence, dict):
        return result

    primary_url = str(evidence.get("primary_item_url") or "")
    for corpus in corpora.values():
        for doc in corpus.get("documents") or []:
            if not isinstance(doc, dict) or str(doc.get("url") or "") != primary_url:
                continue
            source = str(doc.get("published_at_source") or "").strip()
            if source:
                evidence["primary_published_at_source"] = source
            if source == "official_listing_label" and doc.get("listing_label"):
                evidence["primary_listing_label"] = str(doc["listing_label"])[:300]
            return result
    return result


def extended_target_registry(config: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = ranked.ranked_target_registry(config)
    for sid, row in routing.load_primary_targets(config).items():
        result[("primary_target_id", sid)] = {
            "ref_type": "primary_target_id",
            "id": sid,
            "name": str(row.get("publisher") or sid),
            "url": str(row["url"]),
            "tier": str(row.get("tier") or "T1"),
            "status": row.get("status"),
            "enabled": row.get("enabled", True),
            "path_hints": [str(value).casefold() for value in row.get("path_hints") or [] if str(value).strip()],
        }
    return result


def install(instance_id: str) -> None:
    routing.install()
    ranked.install_ranking()
    strict.install_strict_guard(instance_id)
    # Ranking installs its own two-registry target loader. Extend it only after
    # ranking/strict installation so dedicated config targets survive.
    base.target_registry = extended_target_registry
    # Preserve the evidence-only verifier contract while recovering a date that
    # the official listing itself explicitly supplies. No date is inferred from
    # URL shape, file mtime, crawl time, or the secondary signal.
    base.fetch_primary_candidate = listing_date_aware_fetch_primary_candidate
    base.verify_task = listing_date_aware_verify_task


def validate(instance_id: str) -> dict[str, Any]:
    install(instance_id)
    report = base.validate(instance_id)
    config, _ = radar.load_config(instance_id)
    registry = base.target_registry(config)
    hinted = sum(1 for row in registry.values() if row.get("path_hints"))
    return {
        **report,
        "strict_false_positive_guard": True,
        "primary_published_at_required": True,
        "official_listing_label_date_fallback": True,
        "official_listing_label_date_must_be_explicit_terminal": True,
        "title_event_overlap_required": True,
        "candidate_ranking": "LISTING_PATH_THEN_SOURCE_HINTS_THEN_NEWS_STRUCTURE",
        "registered_targets": len(registry),
        "targets_with_path_hints": hinted,
        "dedicated_primary_targets": len(routing.load_primary_targets(config)),
        "publication_authority": "NONE",
    }


def run(instance_id: str, *, write: bool) -> dict[str, Any]:
    install(instance_id)
    state = base.run(instance_id, write=False)
    state["verification_policy"] = {
        "strict_false_positive_guard": True,
        "primary_published_at_required": True,
        "official_listing_label_date_fallback": True,
        "official_listing_label_date_must_be_explicit_terminal": True,
        "max_publication_time_delta_hours": 36,
        "title_event_overlap_required": True,
        "instance_identity_is_not_event_evidence": True,
        "body_only_similarity_rejected": True,
        "primary_candidate_ranking": "LISTING_PATH_THEN_SOURCE_HINTS_THEN_NEWS_STRUCTURE",
        "boundary_safe_signal_routing": True,
        "dedicated_primary_target_registry": True,
    }
    if write:
        config, _ = radar.load_config(instance_id)
        output = ROOT / str(config["primary_verification_state_path"])
        output.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def self_test() -> int:
    tz = ZoneInfo("Europe/Bucharest")
    dmy = listing_label_published_at(
        "APAVIL SA – concurs încasator-cititor, Sector Govora (18.08.2026)",
        tz,
    )
    assert dmy is not None and dmy.isoformat(timespec="seconds") == "2026-08-18T00:00:00+03:00"
    iso = listing_label_published_at("Comunicat oficial (2026-08-18)", tz)
    assert iso is not None and iso.date().isoformat() == "2026-08-18"
    assert listing_label_published_at("Comunicat oficial 18.08.2026", tz) is None
    assert listing_label_published_at("Comunicat (18.08.2026) actualizat", tz) is None
    assert listing_label_published_at("Comunicat oficial (31.02.2026)", tz) is None

    # The recovered listing date is still subject to the existing strict
    # temporal gate; it does not grant publication authority by itself.
    strict.install_strict_guard("valcea")
    derived_doc = {"published_at": dmy.isoformat(timespec="seconds")}
    assert strict.strict_date_compatible(
        {"published_at": "2026-08-18T12:30:00+03:00"},
        derived_doc,
        tz,
    ) is True
    assert strict.strict_date_compatible(
        {"published_at": "2026-08-20T12:30:00+03:00"},
        derived_doc,
        tz,
    ) is False

    assert routing.self_test() == 0
    assert ranked.self_test() == 0
    assert strict.self_test() == 0
    print("LOCAL NEWS OS routed ranked strict primary verifier self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.instance:
        parser.error("--instance is required")
    if args.validate_only:
        print(json.dumps(validate(args.instance), ensure_ascii=False))
        return 0
    state = run(args.instance, write=not args.no_write)
    print(json.dumps({
        "status": "PASS",
        "task_count": state["task_count"],
        "primary_match_count": state["primary_match_count"],
        "no_match_count": state["no_match_count"],
        "unrouted_count": state["unrouted_count"],
        "targets_ok": state["targets_ok"],
        "target_count": state["target_count"],
        "strict_false_positive_guard": True,
        "official_listing_label_date_fallback": True,
        "boundary_safe_signal_routing": True,
        "publication_authority": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
