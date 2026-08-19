#!/usr/bin/env python3
"""Site-owned Story Engine for LOCAL NEWS OS vNext.

Consumes only READY fact kernels whose latest Newsworthiness decision is BUILD or
BUILD_PRIORITY. Materializes an idempotent structured draft in the site-owned
runtime database. The engine never grants publication authority and never writes
repository runtime state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from fact_kernel_engine import FactKernelError, get_fact_kernel
from newsworthiness_engine import (
    NewsworthinessError,
    get_latest_newsworthiness,
    score_fact_kernel,
)
from runtime_store import connect, initialize, register_instance, utc_now
from signal_engine import get_signal

ROOT = Path(__file__).resolve().parents[3]
PUBLICATION_AUTHORITY = "NONE"
ELIGIBLE_ROUTES = {"BUILD", "BUILD_PRIORITY"}
DRAFT_STATE = "DRAFTED"
EVENT_TYPE = "STORY_DRAFT_MATERIALIZED"
REVISION_EVENT_TYPE = "STORY_DRAFT_REVISED"


class StoryEngineError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StoryEngineError(message)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _hash_id(*parts: str, length: int = 24) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:length]


def _truncate(text: str, limit: int) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    clipped = text[: max(1, limit - 1)].rstrip(" ,;:-")
    return f"{clipped}…"


def validate_story_policy(
    editorial_pack: dict[str, Any],
    *,
    instance_id: str,
) -> dict[str, Any]:
    _require(isinstance(editorial_pack, dict), "editorial pack must be an object")
    _require(editorial_pack.get("schema_version") == "2.0", "editorial pack schema mismatch")
    _require(editorial_pack.get("pack_type") == "editorial", "not an editorial pack")
    _require(editorial_pack.get("instance_id") == instance_id, "editorial pack instance mismatch")
    rules = editorial_pack.get("rules") or {}
    _require(rules.get("verified_facts_only") is True, "story engine requires verified_facts_only")
    _require(rules.get("title_only_publishable") is False, "story engine requires title-only fail-closed policy")
    policy = editorial_pack.get("story_engine")
    _require(isinstance(policy, dict), "editorial pack requires story_engine policy")

    default_section = _clean(policy.get("default_section"))
    _require(default_section, "story_engine.default_section is required")
    headline_limit = policy.get("max_headline_chars")
    dek_limit = policy.get("max_dek_chars")
    _require(
        isinstance(headline_limit, int) and not isinstance(headline_limit, bool) and 60 <= headline_limit <= 180,
        "story_engine.max_headline_chars must be between 60 and 180",
    )
    _require(
        isinstance(dek_limit, int) and not isinstance(dek_limit, bool) and 100 <= dek_limit <= 360,
        "story_engine.max_dek_chars must be between 100 and 360",
    )
    section_by_claim_kind = policy.get("section_by_claim_kind") or {}
    _require(isinstance(section_by_claim_kind, dict), "story_engine.section_by_claim_kind must be an object")
    normalized_sections: dict[str, str] = {}
    for key, value in section_by_claim_kind.items():
        claim_kind = _clean(key).upper()
        section = _clean(value)
        _require(claim_kind and section, "story_engine section mapping cannot be empty")
        normalized_sections[claim_kind] = section

    follow_up_label = _clean(policy.get("follow_up_label") or "What next")
    _require(follow_up_label, "story_engine.follow_up_label cannot be empty")
    return {
        "default_section": default_section,
        "max_headline_chars": int(headline_limit),
        "max_dek_chars": int(dek_limit),
        "section_by_claim_kind": normalized_sections,
        "follow_up_label": follow_up_label,
    }


def load_editorial_pack(instance_id: str) -> dict[str, Any]:
    instance_path = ROOT / "local-news-os" / "vnext" / "instances" / instance_id / "instance.json"
    _require(instance_path.is_file(), f"unknown instance: {instance_id}")
    cfg = json.loads(instance_path.read_text(encoding="utf-8"))
    _require(cfg.get("instance_id") == instance_id, "instance directory/id mismatch")
    rel = (cfg.get("packs") or {}).get("editorial")
    _require(isinstance(rel, str) and rel, "instance has no editorial pack")
    path = (ROOT / rel).resolve()
    _require(ROOT.resolve() in path.parents, "editorial pack escapes repository")
    _require(path.is_file(), "editorial pack file missing")
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_story_policy(value, instance_id=instance_id)
    return value


def _decode_draft(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in (
        "body_blocks_json",
        "factbox_json",
        "context_json",
        "source_references_json",
        "follow_up_json",
        "tags_json",
        "entity_bindings_json",
    ):
        data[key.removesuffix("_json")] = json.loads(data.pop(key))
    return data


def get_story_draft(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM story_drafts WHERE instance_id=? AND story_id=?",
        (instance_id, story_id),
    ).fetchone()
    if row is None:
        raise StoryEngineError("story draft not found for instance")
    return _decode_draft(row)


def get_story_draft_by_kernel(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    kernel_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM story_drafts WHERE instance_id=? AND kernel_id=?",
        (instance_id, kernel_id),
    ).fetchone()
    return _decode_draft(row) if row is not None else None


def list_story_drafts(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    bounded = max(1, min(500, int(limit)))
    rows = conn.execute(
        """
        SELECT * FROM story_drafts
        WHERE instance_id=?
        ORDER BY updated_at DESC, story_id ASC
        LIMIT ?
        """,
        (instance_id, bounded),
    ).fetchall()
    return [_decode_draft(row) for row in rows]


def _primary_fact_text(fact: dict[str, Any]) -> str:
    text = _clean(fact.get("claim_text"))
    _require(text, "fact claim_text is required")
    return text


def _compose_headline(facts: list[dict[str, Any]], *, limit: int) -> str:
    preferred = next(
        (fact for fact in facts if _clean(fact.get("claim_kind")).upper() == "HEADLINE_ASSERTION"),
        facts[0],
    )
    return _truncate(_primary_fact_text(preferred), limit)


def _compose_dek(facts: list[dict[str, Any]], *, limit: int) -> str:
    claims: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        text = _primary_fact_text(fact)
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        claims.append(text.rstrip("."))
        if len(claims) >= 3:
            break
    return _truncate(". ".join(claims) + ".", limit)


def _select_section(facts: list[dict[str, Any]], policy: dict[str, Any]) -> str:
    mapping = policy["section_by_claim_kind"]
    for fact in facts:
        claim_kind = _clean(fact.get("claim_kind")).upper()
        if claim_kind in mapping:
            return mapping[claim_kind]
    return policy["default_section"]


def _source_references(provenance: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in provenance:
        evidence_url = _clean(item.get("evidence_url"))
        primary_url = _clean(item.get("primary_target_url"))
        _require(evidence_url and primary_url, "fact-kernel provenance requires primary and evidence URLs")
        key = (primary_url, evidence_url)
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "primary_target_id": _clean(item.get("primary_target_id")),
                "primary_target_url": primary_url,
                "evidence_url": evidence_url,
                "evidence_fingerprint": _clean(item.get("evidence_fingerprint")),
                "source_observed_at": _clean(item.get("source_observed_at")) or None,
                "claim_key": _clean(item.get("claim_key")),
            }
        )
    _require(output, "story draft requires at least one primary source reference")
    return output


def _entity_bindings(signal: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in signal.get("entity_hints") or []:
        text = _clean(item.get("text"))
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "mention": text,
                "kind": _clean(item.get("kind")) or "UNRESOLVED_MENTION",
                "resolution_status": "UNRESOLVED",
                "public_claim_allowed": False,
            }
        )
    return output


def compose_structured_draft(
    *,
    instance_id: str,
    kernel: dict[str, Any],
    signal: dict[str, Any],
    newsworthiness_event: dict[str, Any],
    editorial_pack: dict[str, Any],
) -> dict[str, Any]:
    _require(kernel.get("state") == "READY", "story engine requires READY fact kernel")
    _require(kernel.get("material_fact_ready") is True, "material_fact_ready must be true")
    _require(kernel.get("fact_kernel_ready") is True, "fact_kernel_ready must be true")
    _require(kernel.get("publication_authority") == PUBLICATION_AUTHORITY, "fact kernel unexpectedly carries publication authority")
    payload = newsworthiness_event.get("payload") or {}
    route = _clean(payload.get("route")).upper()
    _require(route in ELIGIBLE_ROUTES, "story engine requires BUILD or BUILD_PRIORITY route")
    _require(payload.get("publication_authority") == PUBLICATION_AUTHORITY, "newsworthiness unexpectedly carries publication authority")
    _require(payload.get("kernel_fingerprint") == kernel.get("fingerprint"), "newsworthiness decision is stale for fact kernel")

    policy = validate_story_policy(editorial_pack, instance_id=instance_id)
    facts = list(kernel.get("facts") or [])
    provenance = list(kernel.get("provenance") or [])
    _require(facts, "story draft requires verified facts")
    _require(provenance, "story draft requires provenance")
    _require(
        any(_clean(fact.get("claim_kind")).upper() != "HEADLINE_ASSERTION" for fact in facts),
        "title-only fact kernel cannot materialize a story draft",
    )

    sources = _source_references(provenance)
    headline = _compose_headline(facts, limit=policy["max_headline_chars"])
    dek = _compose_dek(facts, limit=policy["max_dek_chars"])
    section = _select_section(facts, policy)
    body_blocks = [
        {
            "type": "verified_fact",
            "claim_key": _clean(fact.get("claim_key")),
            "claim_kind": _clean(fact.get("claim_kind")).upper(),
            "text": _primary_fact_text(fact),
            "confidence": int(fact.get("confidence") or 0),
            "verification_result_id": _clean(fact.get("verification_result_id")),
        }
        for fact in facts
    ]
    factbox = [
        {
            "claim_key": block["claim_key"],
            "label": block["claim_kind"],
            "value": block["text"],
            "confidence": block["confidence"],
        }
        for block in body_blocks
    ]
    context = {
        "verification_status": "ALL_MATERIAL_CLAIMS_SUPPORTED",
        "verified_fact_count": len(facts),
        "primary_source_count": len(sources),
        "newsworthiness_route": route,
        "newsworthiness_score": int(payload.get("score") or 0),
        "discovery_signal_id": kernel["signal_id"],
        "discovery_source_is_publication_authority": False,
    }
    follow_up = {
        "label": policy["follow_up_label"],
        "action": "MONITOR_PRIMARY_SOURCES",
        "source_urls": [item["primary_target_url"] for item in sources],
    }
    tags = sorted(
        {
            _clean(fact.get("claim_kind")).lower().replace("_", "-")
            for fact in facts
            if _clean(fact.get("claim_kind"))
        }
    )
    entities = _entity_bindings(signal)
    return {
        "headline": headline,
        "dek": dek,
        "body_blocks": body_blocks,
        "factbox": factbox,
        "context": context,
        "source_references": sources,
        "follow_up": follow_up,
        "section": section,
        "tags": tags,
        "entity_bindings": entities,
        "publication_authority": PUBLICATION_AUTHORITY,
    }


def materialize_story_draft(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    kernel_id: str,
    editorial_pack: dict[str, Any],
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    try:
        kernel = get_fact_kernel(conn, instance_id=instance_id, kernel_id=kernel_id)
    except FactKernelError as exc:
        raise StoryEngineError(str(exc)) from exc
    try:
        newsworthiness = get_latest_newsworthiness(
            conn,
            instance_id=instance_id,
            kernel_id=kernel_id,
        )
    except NewsworthinessError as exc:
        raise StoryEngineError(str(exc)) from exc
    _require(newsworthiness is not None, "story engine requires newsworthiness decision")
    signal = get_signal(conn, instance_id=instance_id, signal_id=str(kernel["signal_id"]))
    structured = compose_structured_draft(
        instance_id=instance_id,
        kernel=kernel,
        signal=signal,
        newsworthiness_event=newsworthiness,
        editorial_pack=editorial_pack,
    )
    decision_payload = newsworthiness["payload"]
    story_id = f"story-{_hash_id(instance_id, kernel_id, kernel['fingerprint'], length=20)}"
    story_fingerprint = _stable_hash(
        {
            "instance_id": instance_id,
            "kernel_id": kernel_id,
            "kernel_fingerprint": kernel["fingerprint"],
        }
    )
    draft_fingerprint = _stable_hash(
        {
            "story_id": story_id,
            "kernel_fingerprint": kernel["fingerprint"],
            "decision_fingerprint": decision_payload.get("decision_fingerprint"),
            "structured": structured,
        }
    )
    now = utc_now()
    existing = get_story_draft_by_kernel(conn, instance_id=instance_id, kernel_id=kernel_id)
    if existing is not None and existing["fingerprint"] == draft_fingerprint:
        return existing, False

    try:
        conn.execute("BEGIN IMMEDIATE")
        if existing is None:
            conn.execute(
                """
                INSERT INTO stories(
                    instance_id, story_id, fingerprint, state, revision,
                    headline, canonical_path, created_at, updated_at
                ) VALUES (?, ?, ?, 'STORY_DRAFTED', 1, ?, NULL, ?, ?)
                """,
                (instance_id, story_id, story_fingerprint, structured["headline"], now, now),
            )
            conn.execute(
                """
                INSERT INTO story_drafts(
                    instance_id, story_id, kernel_id, newsworthiness_event_id,
                    fingerprint, revision, state, headline, dek, body_blocks_json,
                    factbox_json, context_json, source_references_json, follow_up_json,
                    section, tags_json, entity_bindings_json, publication_authority,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 'DRAFTED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NONE', ?, ?)
                """,
                (
                    instance_id,
                    story_id,
                    kernel_id,
                    int(newsworthiness["event_id"]),
                    draft_fingerprint,
                    structured["headline"],
                    structured["dek"],
                    json.dumps(structured["body_blocks"], ensure_ascii=False, sort_keys=True),
                    json.dumps(structured["factbox"], ensure_ascii=False, sort_keys=True),
                    json.dumps(structured["context"], ensure_ascii=False, sort_keys=True),
                    json.dumps(structured["source_references"], ensure_ascii=False, sort_keys=True),
                    json.dumps(structured["follow_up"], ensure_ascii=False, sort_keys=True),
                    structured["section"],
                    json.dumps(structured["tags"], ensure_ascii=False, sort_keys=True),
                    json.dumps(structured["entity_bindings"], ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO runtime_events(
                    instance_id, aggregate_type, aggregate_id, event_type,
                    from_state, to_state, reason, payload_json, engine_version, created_at
                ) VALUES (?, 'story', ?, 'STORY_CREATED', NULL, 'DISCOVERED',
                          'verified kernel selected for story drafting', ?, ?, ?)
                """,
                (
                    instance_id,
                    story_id,
                    json.dumps(
                        {
                            "kernel_id": kernel_id,
                            "story_fingerprint": story_fingerprint,
                            "publication_authority": PUBLICATION_AUTHORITY,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    engine_version,
                    now,
                ),
            )
            event_type = EVENT_TYPE
            previous_state = "DISCOVERED"
            event_reason = "structured draft materialized from verified fact kernel"
        else:
            story_id = str(existing["story_id"])
            story_row = conn.execute(
                "SELECT state, revision FROM stories WHERE instance_id=? AND story_id=?",
                (instance_id, story_id),
            ).fetchone()
            _require(story_row is not None, "story row missing for existing draft")
            _require(story_row["state"] == "STORY_DRAFTED", "cannot revise draft after downstream story state")
            draft_revision = int(existing["revision"])
            cursor = conn.execute(
                """
                UPDATE story_drafts SET
                    newsworthiness_event_id=?, fingerprint=?, revision=revision+1,
                    headline=?, dek=?, body_blocks_json=?, factbox_json=?, context_json=?,
                    source_references_json=?, follow_up_json=?, section=?, tags_json=?,
                    entity_bindings_json=?, updated_at=?
                WHERE instance_id=? AND story_id=? AND revision=?
                """,
                (
                    int(newsworthiness["event_id"]),
                    draft_fingerprint,
                    structured["headline"],
                    structured["dek"],
                    json.dumps(structured["body_blocks"], ensure_ascii=False, sort_keys=True),
                    json.dumps(structured["factbox"], ensure_ascii=False, sort_keys=True),
                    json.dumps(structured["context"], ensure_ascii=False, sort_keys=True),
                    json.dumps(structured["source_references"], ensure_ascii=False, sort_keys=True),
                    json.dumps(structured["follow_up"], ensure_ascii=False, sort_keys=True),
                    structured["section"],
                    json.dumps(structured["tags"], ensure_ascii=False, sort_keys=True),
                    json.dumps(structured["entity_bindings"], ensure_ascii=False, sort_keys=True),
                    now,
                    instance_id,
                    story_id,
                    draft_revision,
                ),
            )
            _require(cursor.rowcount == 1, "story draft changed during revision")
            cursor = conn.execute(
                """
                UPDATE stories
                SET headline=?, revision=revision+1, updated_at=?
                WHERE instance_id=? AND story_id=? AND state='STORY_DRAFTED'
                """,
                (structured["headline"], now, instance_id, story_id),
            )
            _require(cursor.rowcount == 1, "story changed during draft revision")
            event_type = REVISION_EVENT_TYPE
            previous_state = "STORY_DRAFTED"
            event_reason = "structured draft revised after eligible scoring or policy change"

        conn.execute(
            """
            INSERT INTO runtime_events(
                instance_id, aggregate_type, aggregate_id, event_type,
                from_state, to_state, reason, payload_json, engine_version, created_at
            ) VALUES (?, 'story', ?, ?, ?, 'STORY_DRAFTED', ?, ?, ?, ?)
            """,
            (
                instance_id,
                story_id,
                event_type,
                previous_state,
                event_reason,
                json.dumps(
                    {
                        "kernel_id": kernel_id,
                        "kernel_fingerprint": kernel["fingerprint"],
                        "newsworthiness_event_id": int(newsworthiness["event_id"]),
                        "newsworthiness_route": decision_payload.get("route"),
                        "draft_fingerprint": draft_fingerprint,
                        "publication_authority": PUBLICATION_AUTHORITY,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                engine_version,
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_story_draft(conn, instance_id=instance_id, story_id=story_id), True


def _manifest(instance_id: str, domain: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": _stable_hash({"instance_id": instance_id, "domain": domain}),
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def _insert_ready_kernel(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    signal_id: str,
    kernel_id: str,
    fingerprint: str,
    headline: str,
) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO signals(
            instance_id, signal_id, fingerprint, source_id, source_role,
            source_item_fingerprint, source_url, source_title, source_published_at,
            state, publication_authority, material_fact_ready, fact_kernel_ready,
            claim_hints_json, entity_hints_json, created_at, updated_at
        ) VALUES (?, ?, ?, 'fixture-source', 'DISCOVERY', ?, 'https://example.invalid/signal',
                  ?, NULL, 'DISCOVERED', 'NONE', 0, 0, '[]', ?, ?, ?)
        """,
        (
            instance_id,
            signal_id,
            f"sig-{fingerprint}",
            f"src-{fingerprint}",
            headline,
            json.dumps(
                [{"kind": "UNRESOLVED_MENTION", "text": "Example Entity", "resolution_required": True}],
                ensure_ascii=False,
                sort_keys=True,
            ),
            now,
            now,
        ),
    )
    facts = [
        {
            "claim_key": "headline",
            "claim_kind": "HEADLINE_ASSERTION",
            "claim_text": headline,
            "normalized_claim": {"statement": headline},
            "confidence": 98,
            "verification_result_id": "result-headline",
        },
        {
            "claim_key": "money",
            "claim_kind": "MONEY",
            "claim_text": "The verified amount is 100 units",
            "normalized_claim": {"amount": 100, "unit": "units"},
            "confidence": 96,
            "verification_result_id": "result-money",
        },
    ]
    provenance = [
        {
            "claim_key": "headline",
            "verification_result_id": "result-headline",
            "primary_target_id": "authority-one",
            "primary_target_url": "https://authority.example.invalid/notices",
            "evidence_url": "https://authority.example.invalid/notices/1",
            "evidence_fingerprint": "evidence-one",
            "evidence_summary": "Primary source supports the headline claim",
            "source_observed_at": "2026-08-19T10:00:00Z",
            "verdict": "SUPPORTS",
        },
        {
            "claim_key": "money",
            "verification_result_id": "result-money",
            "primary_target_id": "authority-one",
            "primary_target_url": "https://authority.example.invalid/notices",
            "evidence_url": "https://authority.example.invalid/notices/1",
            "evidence_fingerprint": "evidence-one",
            "evidence_summary": "Primary source supports the amount",
            "source_observed_at": "2026-08-19T10:00:00Z",
            "verdict": "SUPPORTS",
        },
    ]
    conn.execute(
        """
        INSERT INTO fact_kernels(
            instance_id, kernel_id, signal_id, fingerprint, state,
            material_fact_ready, fact_kernel_ready, publication_authority,
            facts_json, provenance_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'READY', 1, 1, 'NONE', ?, ?, ?, ?)
        """,
        (
            instance_id,
            kernel_id,
            signal_id,
            fingerprint,
            json.dumps(facts, ensure_ascii=False, sort_keys=True),
            json.dumps(provenance, ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )
    conn.commit()


def _editorial_pack(instance_id: str, *, default_section: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "pack_type": "editorial",
        "instance_id": instance_id,
        "auto_publish_classes": [],
        "human_review_classes": [],
        "rules": {
            "verified_facts_only": True,
            "title_only_publishable": False,
            "one_held_story_blocks_publication": False,
        },
        "newsworthiness": {
            "weights": {
                "local_impact": 20,
                "public_utility": 15,
                "urgency": 15,
                "money": 10,
                "affected_people": 10,
                "novelty": 10,
                "accountability": 10,
                "proximity": 10,
            },
            "routing_thresholds": {
                "BUILD_PRIORITY": 80,
                "BUILD": 55,
                "MONITOR": 30,
            },
        },
        "story_engine": {
            "default_section": default_section,
            "max_headline_chars": 120,
            "max_dek_chars": 220,
            "section_by_claim_kind": {
                "MONEY": "ECONOMY",
                "HEADLINE_ASSERTION": default_section,
            },
            "follow_up_label": "What next",
        },
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "story.sqlite3"
        conn = connect(db)
        initialize(conn)
        engine = "vnext-story-test"
        register_instance(conn, _manifest("alpha-local", "alpha.invalid"), engine_version=engine)
        register_instance(conn, _manifest("beta-local", "beta.invalid"), engine_version=engine)

        _insert_ready_kernel(
            conn,
            instance_id="alpha-local",
            signal_id="alpha-signal",
            kernel_id="alpha-kernel",
            fingerprint="a" * 64,
            headline="Verified local service changes begin Monday",
        )
        alpha_pack = _editorial_pack("alpha-local", default_section="LOCAL")
        score_fact_kernel(
            conn,
            instance_id="alpha-local",
            kernel_id="alpha-kernel",
            dimension_signals={
                "local_impact": 80,
                "public_utility": 90,
                "urgency": 70,
                "money": 60,
                "affected_people": 75,
                "novelty": 65,
                "accountability": 50,
                "proximity": 90,
            },
            editorial_pack=alpha_pack,
            engine_version=engine,
        )
        draft, created = materialize_story_draft(
            conn,
            instance_id="alpha-local",
            kernel_id="alpha-kernel",
            editorial_pack=alpha_pack,
            engine_version=engine,
        )
        assert created is True
        assert draft["state"] == "DRAFTED"
        assert draft["publication_authority"] == "NONE"
        assert draft["section"] == "LOCAL"
        assert draft["headline"] == "Verified local service changes begin Monday"
        assert len(draft["body_blocks"]) == 2
        assert draft["source_references"][0]["evidence_url"].startswith("https://")
        assert draft["entity_bindings"][0]["public_claim_allowed"] is False
        story = conn.execute(
            "SELECT * FROM stories WHERE instance_id='alpha-local' AND story_id=?",
            (draft["story_id"],),
        ).fetchone()
        assert story is not None and story["state"] == "STORY_DRAFTED"
        draft_again, created_again = materialize_story_draft(
            conn,
            instance_id="alpha-local",
            kernel_id="alpha-kernel",
            editorial_pack=alpha_pack,
            engine_version=engine,
        )
        assert created_again is False
        assert draft_again["fingerprint"] == draft["fingerprint"]

        _insert_ready_kernel(
            conn,
            instance_id="beta-local",
            signal_id="beta-signal",
            kernel_id="beta-kernel",
            fingerprint="b" * 64,
            headline="Low-value neutral monitoring item",
        )
        beta_pack = _editorial_pack("beta-local", default_section="COMMUNITY")
        score_fact_kernel(
            conn,
            instance_id="beta-local",
            kernel_id="beta-kernel",
            dimension_signals={
                "local_impact": 10,
                "public_utility": 10,
                "urgency": 5,
                "money": 0,
                "affected_people": 5,
                "novelty": 10,
                "accountability": 5,
                "proximity": 10,
            },
            editorial_pack=beta_pack,
            engine_version=engine,
        )
        try:
            materialize_story_draft(
                conn,
                instance_id="beta-local",
                kernel_id="beta-kernel",
                editorial_pack=beta_pack,
                engine_version=engine,
            )
        except StoryEngineError as exc:
            assert "BUILD or BUILD_PRIORITY" in str(exc)
        else:
            raise AssertionError("MONITOR kernel must not materialize story draft")

        try:
            get_story_draft(conn, instance_id="beta-local", story_id=draft["story_id"])
        except StoryEngineError:
            pass
        else:
            raise AssertionError("cross-instance story draft read must fail")

        event_types = [
            str(row["event_type"])
            for row in conn.execute(
                "SELECT event_type FROM runtime_events WHERE instance_id='alpha-local' AND aggregate_id=? ORDER BY event_id",
                (draft["story_id"],),
            ).fetchall()
        ]
        assert "STORY_CREATED" in event_types
        assert EVENT_TYPE in event_types
        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_STORY_ENGINE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
