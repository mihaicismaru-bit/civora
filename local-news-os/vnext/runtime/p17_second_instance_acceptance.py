#!/usr/bin/env python3
"""P17 same-core acceptance for a freshly bootstrapped neutral LOCAL NEWS OS instance.

This acceptance intentionally lives outside ``core``. It proves that a new
publication can be created from configuration and traverse the validated P0-P16
runtime without editing locality-agnostic core code or performing network
publication.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

VNEXT = Path(__file__).resolve().parents[1]
CORE = VNEXT / "core"
sys.path.insert(0, str(CORE))

from distribution_engine import list_deliveries, validate_channels_pack
from editorial_qa import evaluate_story_draft
from fact_kernel_engine import materialize_fact_kernel, record_verification_result
from instance_bootstrap import build_instance_bundle, initialize_runtime, write_bundle
from media_intelligence import get_story_media_selection
from newsworthiness_engine import score_fact_kernel
from primary_resolver import resolve_signal
from release_control import (
    REQUIRED_GATES,
    get_release_state,
    promote_candidate,
    register_candidate,
    rollback,
    validate_candidate,
)
from runtime_store import connect
from scheduler_engine import (
    SchedulerPolicy,
    build_default_stage_handlers,
    run_tick,
    scheduler_snapshot,
)
from signal_engine import materialize_source_item
from site_publication import publish_story
from source_adapters import SourceDefinition, SourceItem
from story_engine import materialize_story_draft


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _spec() -> dict:
    return {
        "schema_version": "1.0",
        "instance_id": "replica-county",
        "environment": "test",
        "publication": {
            "name": "REPLICA CLAR",
            "short_name": "Replica",
            "canonical_domain": "replica.invalid",
            "story_path_prefix": "/stories",
            "category_path_prefix": "/sections",
        },
        "locale": "en-US",
        "timezone": "UTC",
        "geography": {
            "country_code": "RO",
            "scope": {"type": "county", "name": "Replica County"},
            "aliases": ["Replica"],
            "seed_settlements": ["Alpha City", "Beta Town"],
        },
        "brand": {"name": "REPLICA CLAR", "short_name": "Replica"},
        "runtime": {
            "backend_kind": "sqlite",
            "connection_secret_ref": "REPLICA_RUNTIME_DB",
            "newsroom_secret_ref": "REPLICA_NEWSROOM_TOKEN",
            "public_base_url": "https://replica.invalid",
        },
        "source_candidates": [
            {
                "source_id": "replica-discovery",
                "adapter": "RSS_ATOM",
                "url": "https://discovery.example.test/feed.xml",
                "enabled": False,
            }
        ],
    }


def _outbox_channels(instance_id: str) -> dict:
    pack = {
        "schema_version": "2.0",
        "pack_type": "channels",
        "instance_id": instance_id,
        "channels": [
            {
                "id": "acceptance-outbox",
                "mode": "outbox_only",
                "adapter_id": "outbox_only",
                "product_type": "TEXT_POST",
                "enabled": True,
            }
        ],
    }
    validate_channels_pack(pack, instance_id=instance_id)
    return pack


def _release_manifest(version: str, seed: str) -> dict:
    return {
        "engine_version": version,
        "code_sha": hashlib.sha1(seed.encode("utf-8")).hexdigest(),
        "schema_fingerprint": _sha("schema:" + seed),
        "migration_fingerprint": _sha("migration:" + seed),
    }


def _release_evidence() -> dict:
    return {
        gate: {"pass": True, "evidence_ref": f"p17-second-instance:{gate}:PASS"}
        for gate in REQUIRED_GATES
    }


def run_acceptance() -> dict:
    spec = _spec()
    bundle = build_instance_bundle(spec)
    instance_id = bundle["instance"]["instance_id"]
    assert instance_id == "replica-county"
    assert bundle["instance"]["runtime"]["owner"] == "site_application"
    assert bundle["instance"]["runtime"]["repository_runtime_state_enabled"] is False
    assert bundle["channels"]["channels"] == []
    assert bundle["entities"]["seeds"] == []
    assert bundle["photos"]["assets"] == []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        target = write_bundle(bundle, root=root)
        assert (target / "instance.json").is_file()
        assert len(list((target / "packs").glob("*.json"))) == 8

        db = root / "runtime.sqlite3"
        bootstrap = initialize_runtime(bundle, db_path=db, engine_version="1.0.0")
        assert bootstrap["runtime_owner"] == "site_application"
        assert bootstrap["release_current_engine_version"] == "1.0.0"

        conn = connect(db)
        engine = "p17-second-instance-acceptance"
        discovery = SourceDefinition.from_dict(
            {
                "source_id": "replica-discovery",
                "adapter": "RSS_ATOM",
                "role": "DISCOVERY",
                "url": "https://discovery.example.test/feed.xml",
                "config": {},
            }
        )
        primary = SourceDefinition.from_dict(
            {
                "source_id": "replica-primary",
                "adapter": "JSON_API",
                "role": "PRIMARY",
                "url": "https://authority.example.test/notices",
                "config": {
                    "item_path": "results",
                    "fields": {"id": "id", "url": "url", "title": "title"},
                    "verification": {
                        "authority_class": "OFFICIAL_REGISTER",
                        "claim_kinds": [],
                        "match_terms": [],
                    },
                },
            }
        )
        item = SourceItem(
            source_id="replica-discovery",
            external_id="notice-1",
            url="https://discovery.example.test/story-1",
            title="Public Board Approves Service Schedule Change Worth 20,000 EUR on 19.08.2026",
            published_at="2026-08-19T17:00:00Z",
            summary="The change is documented by the public authority.",
            fingerprint="replica-source-item-1",
        )
        signal, signal_created = materialize_source_item(
            conn,
            instance_id=instance_id,
            source=discovery,
            item=item,
            engine_version=engine,
        )
        assert signal_created is True
        assert signal["publication_authority"] == "NONE"

        tasks = resolve_signal(
            conn,
            instance_id=instance_id,
            signal_id=signal["signal_id"],
            source_definitions=[discovery, primary],
            engine_version=engine,
        )
        assert tasks and all(task["state"] == "TARGETS_READY" for task in tasks)
        target_ids = {
            candidate["target_id"]
            for task in tasks
            for candidate in task["target_candidates"]
        }
        assert len(target_ids) == 1
        target_id = next(iter(target_ids))

        for task in tasks:
            record_verification_result(
                conn,
                instance_id=instance_id,
                task_id=task["task_id"],
                target_id=target_id,
                verdict="SUPPORTS",
                evidence_url="https://authority.example.test/notices/1",
                evidence_fingerprint=_sha("evidence:" + task["claim_key"]),
                evidence_summary=f"Primary register supports {task['claim_kind']}",
                confidence=98,
                normalized_claim={"value": task["claim_text"]},
                source_observed_at="2026-08-19T17:05:00Z",
                engine_version=engine,
            )

        kernel, kernel_created = materialize_fact_kernel(
            conn,
            instance_id=instance_id,
            signal_id=signal["signal_id"],
            engine_version=engine,
        )
        assert kernel_created is True
        assert kernel["state"] == "READY"
        assert kernel["publication_authority"] == "NONE"

        dimensions = {
            "local_impact": 95,
            "public_utility": 95,
            "urgency": 85,
            "money": 90,
            "affected_people": 85,
            "novelty": 80,
            "accountability": 90,
            "proximity": 95,
        }
        score_event, score_created = score_fact_kernel(
            conn,
            instance_id=instance_id,
            kernel_id=kernel["kernel_id"],
            dimension_signals=dimensions,
            editorial_pack=bundle["editorial"],
            engine_version=engine,
        )
        assert score_created is True
        assert score_event["payload"]["route"] in {"BUILD", "BUILD_PRIORITY"}
        assert score_event["payload"]["publication_authority"] == "NONE"

        draft, draft_created = materialize_story_draft(
            conn,
            instance_id=instance_id,
            kernel_id=kernel["kernel_id"],
            editorial_pack=bundle["editorial"],
            engine_version=engine,
        )
        assert draft_created is True
        assert draft["publication_authority"] == "NONE"
        assert len(draft["body_blocks"]) >= 2

        qa, qa_created = evaluate_story_draft(
            conn,
            instance_id=instance_id,
            story_id=draft["story_id"],
            editorial_pack=bundle["editorial"],
            engine_version=engine,
        )
        assert qa_created is True
        assert qa["outcome"] == "QA_PASSED"

        publication, publication_created = publish_story(
            conn,
            instance_id=instance_id,
            story_id=draft["story_id"],
            publication_pack=bundle["publication"],
            engine_version=engine,
        )
        assert publication_created is True
        assert publication["canonical_path"].startswith("/stories/")

        runtime_packs = dict(bundle)
        runtime_packs["channels"] = _outbox_channels(instance_id)
        dimension_provider = lambda _conn, _instance_id, _kernel_id: dict(dimensions)
        handlers = build_default_stage_handlers(
            packs=runtime_packs,
            source_definitions=[discovery, primary],
            dimension_provider=dimension_provider,
        )
        policy = SchedulerPolicy(
            batch_size=20,
            lease_seconds=60,
            base_backoff_seconds=1,
            max_backoff_seconds=5,
            max_attempts=3,
        )
        first_tick = run_tick(
            conn,
            instance_id=instance_id,
            engine_version=engine,
            packs=runtime_packs,
            handlers=handlers,
            owner_id="p17-acceptance",
            policy=policy,
        )
        assert first_tick["status"] == "PASS"
        assert first_tick["retry"] == 0 and first_tick["needs_attention"] == 0
        assert first_tick["done"] >= 2

        media = get_story_media_selection(
            conn,
            instance_id=instance_id,
            story_id=draft["story_id"],
            usage_scope="SITE_HERO",
        )
        assert media is not None
        assert media["selection_kind"] == "EDITORIAL_CARD"

        deliveries = list_deliveries(conn, instance_id=instance_id)
        assert len(deliveries) == 1
        assert deliveries[0]["status"] == "HELD"
        assert deliveries[0]["remote_verified"] in (0, False)

        second_tick = run_tick(
            conn,
            instance_id=instance_id,
            engine_version=engine,
            packs=runtime_packs,
            handlers=handlers,
            owner_id="p17-acceptance",
            policy=policy,
        )
        assert second_tick["claimed"] == 0
        snapshot = scheduler_snapshot(conn, instance_id=instance_id)
        assert snapshot["job_counts"].get("RETRY", 0) == 0
        assert snapshot["job_counts"].get("NEEDS_ATTENTION", 0) == 0

        candidate, candidate_created = register_candidate(
            conn,
            instance_id=instance_id,
            manifest=_release_manifest("1.1.0", "p17-replica-artifact"),
            engine_version=engine,
        )
        assert candidate_created is True
        validated, validated_now = validate_candidate(
            conn,
            instance_id=instance_id,
            candidate_id=candidate["candidate_id"],
            evidence=_release_evidence(),
            engine_version=engine,
        )
        assert validated_now is True and validated["status"] == "VALIDATED"
        promoted = promote_candidate(
            conn,
            instance_id=instance_id,
            candidate_id=candidate["candidate_id"],
            engine_version=engine,
        )
        assert promoted["current_engine_version"] == "1.1.0"
        assert promoted["previous_engine_version"] == "1.0.0"
        rolled = rollback(
            conn,
            instance_id=instance_id,
            reason="P17 acceptance rollback drill",
            engine_version=engine,
        )
        assert rolled["current_engine_version"] == "1.0.0"
        assert get_release_state(conn, instance_id=instance_id)["current_engine_version"] == "1.0.0"

        counts = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE instance_id=?", (instance_id,)
            ).fetchone()[0]
            for table in (
                "signals",
                "verification_tasks",
                "verification_results",
                "fact_kernels",
                "story_drafts",
                "editorial_qa_decisions",
                "story_publications",
                "story_media_selections",
                "channel_products",
                "scheduler_ticks",
                "release_history",
            )
        }
        assert all(value > 0 for value in counts.values())
        conn.close()

    return {
        "instance_id": instance_id,
        "runtime_owner": "site_application",
        "repository_runtime_state_enabled": False,
        "story_state": "PUBLISHED",
        "media_selection": "EDITORIAL_CARD",
        "distribution_mode": "outbox_only",
        "network_publication_attempted": False,
        "scheduler_second_tick_claimed": 0,
        "release_rollback_restored": "1.0.0",
        "counts": counts,
    }


def main() -> int:
    result = run_acceptance()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print("LOCAL_NEWS_OS_VNEXT_P17_SECOND_INSTANCE_ACCEPTANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
