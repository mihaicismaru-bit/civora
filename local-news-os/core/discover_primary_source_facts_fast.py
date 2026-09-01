#!/usr/bin/env python3
"""Low-latency primary-source discovery for live newsrooms.

This is a bounded-parallel execution adapter over SOURCE_PACK_V1 and the strict
publication-date guard. The underlying crawler still admits only source title,
article publication date and canonical source URL. That narrow kernel is a
newsroom radar signal, never reader-facing copy: it remains held until a full
fact kernel is built from the source body.

Transport failures remain correlated by source host for diagnostics and never
weaken TLS or evidence semantics.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

CORE = Path(__file__).resolve().parent
ROOT = CORE.parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import discover_primary_source_facts as base  # noqa: E402
import discovery_health as discovery_health  # noqa: E402

DEFAULT_WORKERS = 6
MAX_WORKERS = 8
HOST_INCIDENT_MIN_FAILURES = 2
SOURCE_NOTICE_INPUT_SCOPES = {
    "source_title_and_publication_date_only",
    "title_date_source_only",
}
SOURCE_NOTICE_SCOPE = "verified_source_notice_radar_only"
SOURCE_NOTICE_PRIORITY_FLOORS = {
    "SIGURANȚĂ": 99,
    "SĂNĂTATE": 96,
    "INFRASTRUCTURĂ": 95,
    "MOBILITATE": 94,
    "ENERGIE": 94,
    "ADMINISTRAȚIE": 92,
    "ECONOMIE": 90,
    "EDUCAȚIE": 88,
    "MEDIU": 88,
    "EVENIMENTE": 86,
    "CULTURĂ": 84,
    "SPORT": 84,
}


def normalized_source_host(url: str) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower().strip(".")
    return host.removeprefix("www.")


def correlate_host_failures(sources: list[dict], rows: list[dict]) -> list[dict]:
    """Group simultaneous failed source rows that share one source host.

    The result is diagnostic only. It never changes source eligibility, retries,
    TLS verification, fact admission, or publication. A group is emitted only
    when at least two configured sources on the same normalized host fail in the
    same discovery observation, which avoids turning isolated failures into
    misleading host incidents.
    """
    source_by_id = {str(source.get("id")): source for source in sources}
    grouped: dict[str, dict] = {}
    for row in rows:
        if bool(row.get("listing_ok")):
            continue
        source_id = str(row.get("source_id") or "")
        source = source_by_id.get(source_id)
        if not source:
            continue
        host = normalized_source_host(str(source.get("url") or ""))
        if not host:
            continue
        group = grouped.setdefault(host, {
            "host": host,
            "status": "DEGRADED_HOST",
            "failed_source_ids": [],
            "error_categories": set(),
            "correlated_failure": True,
            "editorial_semantics_changed": False,
        })
        group["failed_source_ids"].append(source_id)
        category = discovery_health.error_category(row.get("error")) or "UNKNOWN_ERROR"
        group["error_categories"].add(category)

    incidents: list[dict] = []
    for host in sorted(grouped):
        group = grouped[host]
        source_ids = sorted(set(group["failed_source_ids"]))
        if len(source_ids) < HOST_INCIDENT_MIN_FAILURES:
            continue
        incidents.append({
            "host": host,
            "status": group["status"],
            "failed_source_count": len(source_ids),
            "failed_source_ids": source_ids,
            "error_categories": sorted(group["error_categories"]),
            "correlated_failure": True,
            "editorial_semantics_changed": False,
        })
    return incidents


def _parse_fact_time(value: str, timezone: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def source_notice_brief(fact: dict, timezone: ZoneInfo) -> dict:
    """Normalize a title/date/source signal for the internal newsroom radar.

    The signal contains too little evidence for an article. It therefore carries
    no generated reader copy and cannot pass a public story gate until a full,
    claim-level fact kernel replaces it.
    """
    if fact.get("auto_scope") not in SOURCE_NOTICE_INPUT_SCOPES:
        return fact
    sources = [row for row in fact.get("sources", []) if isinstance(row, dict) and row.get("url")]
    if not sources:
        return fact
    source = sources[0]
    headline = str(fact.get("headline") or "").strip()
    if not headline:
        return fact
    try:
        published = _parse_fact_time(str(fact.get("valid_from") or ""), timezone)
    except Exception:
        return fact
    section = str(fact.get("section") or "ȘTIRI").upper()
    floor = SOURCE_NOTICE_PRIORITY_FLOORS.get(section, 86)

    result = dict(fact)
    result["source_title"] = headline
    result["auto_scope"] = SOURCE_NOTICE_SCOPE
    result["brief_kind"] = "primary_source_radar_signal"
    result["status"] = "candidate"
    result["material_fact_gate"] = "HOLD_TITLE_DATE_ONLY"
    result["priority"] = max(int(fact.get("priority") or 0), floor)
    result["dek"] = ""
    result["paragraphs"] = []
    result["reader_facing_copy_authorized"] = False
    result["source_notice_contract"] = {
        "verified_fields": ["source_title", "publication_date", "publisher", "source_url"],
        "source_body_material_claims_autopublished": False,
        "publication_eligibility": "radar_only_until_full_fact_kernel",
    }
    return result


def materialize_source_notice_briefs(facts: list[dict], timezone: ZoneInfo) -> list[dict]:
    return [source_notice_brief(fact, timezone) for fact in facts]


def run(instance_id: str, output: Path, state: Path, workers: int) -> int:
    instance_path = ROOT / "local-news-os" / "instances" / instance_id / "instance.json"
    instance = base.load_json(instance_path)
    if instance.get("instance_id") != instance_id:
        raise ValueError("instance id mismatch")

    resolved = base.resolve(instance_id)
    registry = base.to_legacy_registry(instance_id, resolved)
    sources = list(registry.get("sources", []))
    policy = registry.get("policy", {})

    output.parent.mkdir(parents=True, exist_ok=True)
    state.parent.mkdir(parents=True, exist_ok=True)

    legacy = base.load_legacy_module()
    timezone = ZoneInfo(str(instance["timezone"]))
    base.install_date_guard(legacy, timezone)
    canonical_domain = str(instance["canonical_domain"])
    brand_name = str(instance["brand"]["name"])
    now = datetime.now(timezone)

    # Keep the compatibility module's environment identical to the serial path.
    with tempfile.TemporaryDirectory(prefix=f"local-news-os-fast-{instance_id}-") as tmp:
        registry_path = Path(tmp) / "news_sources.json"
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        legacy.REGISTRY = registry_path
        legacy.OUT = output
        legacy.STATE = state
        legacy.TZ = timezone
        legacy.UA = f"Mozilla/5.0 LOCAL-NEWS-OS/{instance_id} (+https://{canonical_domain}/)"

        bounded_workers = max(1, min(int(workers), MAX_WORKERS, max(1, len(sources))))
        results: dict[str, tuple[list[dict], dict]] = {}
        errors: dict[str, Exception] = {}

        with ThreadPoolExecutor(max_workers=bounded_workers, thread_name_prefix=f"ln-{instance_id}") as pool:
            futures = {
                pool.submit(legacy.discover_source, source, now, policy): source
                for source in sources
            }
            for future in as_completed(futures):
                source = futures[future]
                source_id = str(source["id"])
                try:
                    results[source_id] = future.result()
                except Exception as exc:  # isolate one failing source, preserving the rest
                    errors[source_id] = exc

    # Deterministic fold in SOURCE_PACK order, independent of completion order.
    all_facts: list[dict] = []
    health: list[dict] = []
    for source in sources:
        source_id = str(source["id"])
        if source_id in results:
            facts, row = results[source_id]
            all_facts.extend(facts)
            health.append(row)
        else:
            exc = errors.get(source_id, RuntimeError("source worker produced no result"))
            health.append({
                "source_id": source_id,
                "listing_ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "facts": 0,
            })

    deduped_facts = legacy.dedupe_repeated_headlines(all_facts)
    facts = materialize_source_notice_briefs(deduped_facts, timezone)
    result_doc = {
        "schema_version": "1.3",
        "generated_at": now.isoformat(timespec="seconds"),
        "generator": "primary_source_notice_parallel_v2",
        "facts": facts,
        "policy": {
            "llm_required": False,
            "external_paid_api_required": False,
            "autopublished_fields": ["source_title", "publication_date", "source_url", "publisher"],
            "article_body_material_facts_autopublish": False,
            "verified_source_notice_briefs_enabled": True,
            "source_notice_scope": SOURCE_NOTICE_SCOPE,
            "repeated_headline_policy": "keep_newest",
            "automatic_priority_ceiling_before_notice_promotion": legacy.AUTO_PRIORITY_CEILING,
            "notice_priority_floors": SOURCE_NOTICE_PRIORITY_FLOORS,
            "bounded_parallel_source_discovery": True,
            "max_parallel_sources": bounded_workers,
            "parallelism_changes_editorial_semantics": False,
        },
    }
    output.write_text(json.dumps(result_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    host_incidents = correlate_host_failures(sources, health)
    state_doc = {
        "schema_version": "1.4",
        "observed_at": now.isoformat(timespec="seconds"),
        "execution_mode": "bounded_parallel",
        "max_parallel_sources": bounded_workers,
        "sources_total": len(health),
        "sources_ok": sum(1 for row in health if row.get("listing_ok")),
        "facts_admitted": len(facts),
        "source_notice_briefs": sum(1 for fact in facts if fact.get("auto_scope") == SOURCE_NOTICE_SCOPE),
        "facts_before_cross_source_headline_dedupe": len(all_facts),
        "host_incident_count": len(host_incidents),
        "host_incidents": host_incidents,
        "sources": health,
    }
    state.write_text(json.dumps(state_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    base.brand_output(output, instance_id, brand_name)
    base.tag_state(state, instance_id)
    print(json.dumps({
        "status": "PASS",
        "mode": "bounded_parallel",
        "workers": bounded_workers,
        "sources_ok": state_doc["sources_ok"],
        "sources_total": state_doc["sources_total"],
        "facts_admitted": len(facts),
        "source_notice_briefs": state_doc["source_notice_briefs"],
        "host_incidents": len(host_incidents),
    }, ensure_ascii=False))
    return 0


def self_test() -> int:
    assert 1 <= DEFAULT_WORKERS <= MAX_WORKERS
    assert base.validate_only("valcea")["source_contract"] == "SOURCE_PACK_V1"
    assert base.strict_autopublish_date(
        '<meta property="article:published_time" content="2026-08-16T07:30:00+03:00">',
        ZoneInfo("Europe/Bucharest"),
    ) is not None
    assert base.strict_autopublish_date(
        '<h1>Eveniment 16.08.2026</h1>',
        ZoneInfo("Europe/Bucharest"),
    ) is None

    tz = ZoneInfo("Europe/Bucharest")
    candidate = {
        "id": "auto-test",
        "auto_generated": True,
        "auto_scope": "source_title_and_publication_date_only",
        "section": "ADMINISTRAȚIE",
        "priority": 76,
        "headline": "Primăria publică o informare nouă pentru locuitorii municipiului",
        "dek": "candidate",
        "paragraphs": [],
        "valid_from": "2026-08-26T09:00:00+03:00",
        "sources": [{"name": "Primăria Test", "url": "https://example.test/stire", "tier": "T1"}],
    }
    brief = source_notice_brief(candidate, tz)
    assert brief["auto_scope"] == SOURCE_NOTICE_SCOPE
    assert brief["brief_kind"] == "primary_source_radar_signal"
    assert brief["status"] == "candidate"
    assert brief["material_fact_gate"] == "HOLD_TITLE_DATE_ONLY"
    assert brief["priority"] >= SOURCE_NOTICE_PRIORITY_FLOORS["ADMINISTRAȚIE"]
    assert brief["paragraphs"] == []
    assert brief["reader_facing_copy_authorized"] is False
    assert brief["sources"][0]["url"] == candidate["sources"][0]["url"]
    assert brief["source_notice_contract"]["source_body_material_claims_autopublished"] is False

    sources = [
        {"id": "one", "url": "https://example.test/news"},
        {"id": "two", "url": "https://www.example.test/decisions"},
        {"id": "three", "url": "https://other.test/news"},
    ]
    rows = [
        {"source_id": "one", "listing_ok": False,
         "error": "URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>"},
        {"source_id": "two", "listing_ok": False,
         "error": "URLError: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>"},
        {"source_id": "three", "listing_ok": False,
         "error": "socket timeout"},
    ]
    incidents = correlate_host_failures(sources, rows)
    assert incidents == [{
        "host": "example.test",
        "status": "DEGRADED_HOST",
        "failed_source_count": 2,
        "failed_source_ids": ["one", "two"],
        "error_categories": ["SSL_CERTIFICATE"],
        "correlated_failure": True,
        "editorial_semantics_changed": False,
    }]
    print("LOCAL NEWS OS bounded-parallel discovery self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", default="valcea")
    parser.add_argument("--output")
    parser.add_argument("--state")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.output or not args.state:
        parser.error("--output and --state are required")
    return run(args.instance, Path(args.output), Path(args.state), args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
