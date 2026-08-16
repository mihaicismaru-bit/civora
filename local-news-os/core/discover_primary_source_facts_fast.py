#!/usr/bin/env python3
"""Low-latency, fail-closed primary-source discovery for live newsrooms.

This is a bounded-parallel execution adapter over the same SOURCE_PACK_V1,
publication-date guard and legacy discovery semantics used by
`discover_primary_source_facts.py`. It changes latency only, never the
publication scope: automatically discovered records remain title/date/source
candidates and cannot become full stories by themselves.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CORE = Path(__file__).resolve().parent
ROOT = CORE.parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import discover_primary_source_facts as base  # noqa: E402

DEFAULT_WORKERS = 6
MAX_WORKERS = 8


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
                except Exception as exc:  # fail closed per source, preserving other sources
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

    facts = legacy.dedupe_repeated_headlines(all_facts)
    result_doc = {
        "schema_version": "1.2",
        "generated_at": now.isoformat(timespec="seconds"),
        "generator": "primary_source_title_date_zero_llm_parallel_v1",
        "facts": facts,
        "policy": {
            "llm_required": False,
            "external_paid_api_required": False,
            "autopublished_fields": ["source_title", "publication_date", "source_url"],
            "article_body_material_facts_autopublish": False,
            "repeated_headline_policy": "keep_newest",
            "automatic_priority_ceiling": legacy.AUTO_PRIORITY_CEILING,
            "bounded_parallel_source_discovery": True,
            "max_parallel_sources": bounded_workers,
            "parallelism_changes_editorial_semantics": False,
        },
    }
    output.write_text(json.dumps(result_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_doc = {
        "schema_version": "1.2",
        "observed_at": now.isoformat(timespec="seconds"),
        "execution_mode": "bounded_parallel",
        "max_parallel_sources": bounded_workers,
        "sources_total": len(health),
        "sources_ok": sum(1 for row in health if row.get("listing_ok")),
        "facts_admitted": len(facts),
        "facts_before_cross_source_headline_dedupe": len(all_facts),
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
